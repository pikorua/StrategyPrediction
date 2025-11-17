"""
Z3Alpha-LM (QF_NIA Full Version)
--------------------------------
Train a grammar-constrained transformer (with GNN encoder)
to generate complex Z3 strategies from SMT2 problems.

Supports nested/parameterized tactics such as:
(then elim-uncnstr solve-eqs elim-uncnstr lia2card smt)
(then (using-params smt :random_seed 300))
(then (using-params propagate-values :push_ite_bv true)
      (using-params simplify :elim_and true :blast_distinct true)
      elim-uncnstr propagate-values smt)
"""

import os, re, csv, torch, torch.nn as nn, torch.optim as optim, torch.nn.functional as F
import networkx as nx
from lark import Lark, UnexpectedInput
from torch.utils.data import Dataset, DataLoader
from torch_geometric.data import Data, Batch as GeometricBatch
from torch_geometric.nn import GINConv, global_add_pool
from pysmt.smtlib.parser import SmtLibParser

# =====================================================
# 1️⃣ Grammar — Nested & Parameterized Strategies
# =====================================================
GRAMMAR = r"""
    start: strategy
    strategy: tactic
            | "(" "then" strategy_seq ")"
            | "(" "par-or" strategy_seq ")"
    strategy_seq: strategy | strategy strategy_seq
    tactic: ATOM | using_params
    using_params: "(" "using-params" ATOM param_list ")"
    param_list: (":" NAME (ATOM | NUMBER))* 
    ATOM: /[A-Za-z0-9_\-]+/
    NAME: /[A-Za-z0-9_\-]+/
    NUMBER: /[0-9]+/
    %import common.WS
    %ignore WS
"""
grammar_parser = Lark(GRAMMAR, parser="lalr")

# =====================================================
# 2️⃣ Vocabulary — All known Z3 tactics and params
# =====================================================
BASE_TOKENS = ["(", ")", "then", "par-or", "using-params", ":", "<PAD>", "<SOS>", "<EOS>", "<UNK>"]

TACTICS = [
    # general
    "simplify", "solve-eqs", "propagate-values", "elim-uncnstr", "ctx-simplify",
    "card2bv", "lia2card", "qfnra-nlsat", "nla2bv", "cofactor-term-ite", "qfnia",
    # solvers
    "smt", "qfbv", "qfnra", "lia2card", "ctx-simplify",
    # special internal ones
    "degree-shift", "bit-blast", "nla2card", "elim-term-ite",
]

PARAMS = [
    ":random_seed", ":elim_and", ":blast_distinct", ":local_ctx",
    ":pull_cheap_ite", ":som", ":flat", ":hi_div0", ":hoist_mul",
    ":push_ite_bv", ":inline_vars", ":factor", ":seed", ":nla2bv_max_bv_size"
]

VOCAB = BASE_TOKENS + list(sorted(set(t.replace(":", "") for t in TACTICS + PARAMS)))
tok2id = {t: i for i, t in enumerate(VOCAB)}
id2tok = {i: t for t, i in tok2id.items()}

# =====================================================
# 3️⃣ Tokenizer + Grammar-Constrained Mask
# =====================================================
def tokenize_strategy(s: str):
    toks = re.findall(r"[\w\-]+|:?\w+|\(|\)", s)
    return [tok2id.get(t.strip(":"), tok2id["<UNK>"]) for t in toks if t.strip()]


def valid_next_tokens(prefix_tokens):
    """
    Context-aware grammar mask:
    - Prevents combinators (then, par-or, using-params) from appearing as tactic arguments
    - Ensures parameter lists are only inside using-params
    """
    mask = torch.zeros(len(VOCAB), dtype=torch.bool)
    last = prefix_tokens[-1] if prefix_tokens else "<SOS>"
    open_parens = prefix_tokens.count("(") - prefix_tokens.count(")")
    inside_params = "using-params" in prefix_tokens and prefix_tokens[-1] != ")"

    allowed = []

    # ---- Beginning of a strategy ----
    if last in ["<SOS>", "("]:
        allowed = ["then", "par-or"] + [t for t in VOCAB if t not in BASE_TOKENS]

    # ---- After 'then' or 'par-or' ----
    elif last in ["then", "par-or"]:
        allowed = [t for t in VOCAB if t not in ["then", "par-or", "using-params", "<PAD>", "<SOS>", "<EOS>"]]
        allowed += ["("]  # allow nested tactic group

    # ---- Inside using-params ----
    elif inside_params:
        allowed = [p.replace(":", "") for p in PARAMS] + ["true", "false", ")", "NUMBER"]

    # ---- After a parameter name ----
    elif last in [p.replace(":", "") for p in PARAMS]:
        allowed = ["true", "false", "NUMBER", ")"]

    # ---- After tactic or ')' ----
    elif last in [t for t in VOCAB if t not in BASE_TOKENS] + [")"]:
        allowed = [")", "(", "then", "par-or"]

    # ---- Fallback ----
    else:
        allowed = [")"]

    for tok in allowed:
        if tok in tok2id:
            mask[tok2id[tok]] = True

    # Disallow combinators too deep (avoid nested `then`)
    if prefix_tokens.count("then") > 2:
        mask[tok2id["then"]] = False
        mask[tok2id["par-or"]] = False

    return mask


# =====================================================
# 4️⃣ SMT2 Parser → Graph
# =====================================================
TYPE_MAP = {"variable": 0, "constant": 1, "operator": 2, "other": 3}

def get_node_type(name):
    if re.match(r"^\d+$", name):
        return "constant"
    elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return "variable"
    else:
        return "operator"

def encode_node_type(ntype):
    v = torch.zeros(len(TYPE_MAP))
    v[TYPE_MAP[ntype]] = 1.0
    return v

def parse_s_expr(expr, graph, parent=None):
    expr = expr.strip()
    if expr.startswith("("):
        inner = expr[1:-1].strip()
        parts = re.split(r"\s+", inner, maxsplit=1)
        func = parts[0]
        idx = len(graph)
        graph.add_node(idx, label=func, type="operator")
        if parent is not None:
            graph.add_edge(parent, idx)
        if len(parts) > 1:
            args = re.findall(r"\([^\(\)]*\)|[^\s()]+", parts[1])
            for arg in args:
                parse_s_expr(arg, graph, idx)
        return idx
    else:
        idx = len(graph)
        graph.add_node(idx, label=expr, type=get_node_type(expr))
        if parent is not None:
            graph.add_edge(parent, idx)
        return idx

def smt_to_graph(file_path):
    graph = nx.DiGraph()
    with open(file_path) as f:
        content = f.read()
    asserts = re.findall(r"\(assert\s+(.*?)\)", content, flags=re.DOTALL)
    for a in asserts:
        parse_s_expr(a, graph)
    if len(graph) == 0:
        graph.add_node(0, label="empty", type="other")
    x = torch.stack([encode_node_type(graph.nodes[n]["type"]) for n in graph.nodes])
    edges = list(graph.edges)
    edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous() if edges else torch.zeros((2, 0), dtype=torch.long)
    return Data(x=x, edge_index=edge_index)

# =====================================================
# 5️⃣ Dataset + Collate
# =====================================================
class SMTStrategyDataset(Dataset):
    def __init__(self, csv_path):
        self.data = []
        with open(csv_path) as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                self.data.append(row)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        smt_path, strategy = self.data[i][0], self.data[i][1]
        runtime = float(self.data[i][2]) if len(self.data[i]) > 2 else 1.0
        graph = smt_to_graph(smt_path)
        tokens = torch.tensor([tok2id["<SOS>"]] + tokenize_strategy(strategy) + [tok2id["<EOS>"]])
        weight = torch.tensor(1.0 / (runtime + 1e-3), dtype=torch.float32)
        return graph, tokens, weight

def collate_fn(batch):
    graphs, tokens_list, weights = zip(*batch)
    batched_graph = GeometricBatch.from_data_list(graphs)
    max_len = max(len(t) for t in tokens_list)
    batch_size = len(tokens_list)
    padded = torch.full((max_len, batch_size), tok2id["<PAD>"], dtype=torch.long)
    for i, t in enumerate(tokens_list):
        padded[:len(t), i] = t
    weights = torch.stack(weights)
    return batched_graph, padded, weights

# =====================================================
# 6️⃣ Model
# =====================================================
class GNNEncoder(nn.Module):
    def __init__(self, in_dim=4, hidden=256, num_layers=4, dropout=0.2):
        super().__init__()
        self.input_proj = nn.Linear(in_dim, hidden)
        self.layers = nn.ModuleList()
        self.bns = nn.ModuleList()
        for _ in range(num_layers):
            mlp = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, hidden))
            self.layers.append(GINConv(mlp))
            self.bns.append(nn.BatchNorm1d(hidden))
        self.dropout = nn.Dropout(dropout)
        self.out = nn.Linear(hidden, hidden)

    def forward(self, x, edge_index, batch):
        x = self.input_proj(x)
        for conv, bn in zip(self.layers, self.bns):
            res = x
            x = F.relu(bn(conv(x, edge_index)))
            x = x + res
            x = self.dropout(x)
        x = global_add_pool(x, batch)
        return self.out(x)

class GrammarDecoder(nn.Module):
    def __init__(self, vocab_size, hidden=256, layers=6, heads=8, dropout=0.2):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, hidden)
        self.pos_emb = nn.Embedding(512, hidden)
        dec_layer = nn.TransformerDecoderLayer(d_model=hidden, nhead=heads, dropout=dropout, activation="gelu")
        self.dec = nn.TransformerDecoder(dec_layer, num_layers=layers)
        self.out = nn.Linear(hidden, vocab_size)

    def forward(self, tgt, memory):
        seq_len, batch = tgt.shape
        pos = torch.arange(seq_len, device=tgt.device).unsqueeze(1)
        tgt_emb = self.embed(tgt) + self.pos_emb(pos)
        mask = nn.Transformer.generate_square_subsequent_mask(seq_len).to(tgt.device)

        # decoder output hidden states
        hidden = self.dec(tgt_emb, memory, tgt_mask=mask)  # [T, B, H]
        logits = self.out(hidden)  # [T, B, V]

        return logits, hidden


# =====================================================
# 🧠 Z3Transformer (large version)
# =====================================================
class Z3Transformer(nn.Module):
    def __init__(self, vocab_size=len(VOCAB), hidden=512):
        super().__init__()
        # Stronger encoder
        self.encoder = GNNEncoder(in_dim=4, hidden=hidden, num_layers=5, dropout=0.2)
        # Larger decoder
        self.decoder = GrammarDecoder(vocab_size, hidden=hidden, layers=8, heads=8, dropout=0.2)
        # Grammar-type classifier (structure / tactic / param)
        self.classifier = nn.Linear(hidden, 3)
        self.hidden = hidden

    def forward(self, graph, tgt):
        mem = self.encoder(graph.x, graph.edge_index, graph.batch)  # [B, H]
        mem_seq = mem.unsqueeze(0).repeat(tgt.size(0), 1, 1)  # [T, B, H]
        logits, hidden = self.decoder(tgt, mem_seq)  # both returned now
        class_logits = self.classifier(hidden)  # [T, B, 3]
        return logits, class_logits


# =====================================================
# 🏋️ Training loop with grammar-type loss & curriculum
# =====================================================
def soft_syntax_score(tokens):
    """
    Returns a soft syntax validity score between 0 and 1.
    The score increases with:
    - Balanced parentheses
    - Proper use of structural tokens
    - Avoidance of malformed patterns
    """
    if not tokens:
        return 0.0

    # Remove padding or special tokens
    toks = [t for t in tokens if t not in ["<PAD>", "<SOS>", "<EOS>"]]
    n = len(toks)
    if n == 0:
        return 0.0

    # 1️⃣ Parenthesis balance ratio
    opens = toks.count("(")
    closes = toks.count(")")
    balance = 1.0 - (abs(opens - closes) / max(opens + closes + 1e-5, 1))

    # 2️⃣ Structure token ratio
    structure = ["(", ")", "then", "par-or", "using-params"]
    struct_ratio = sum(t in structure for t in toks) / n

    # 3️⃣ Local pattern validity — count good patterns like "( then"
    good_patterns = 0
    for i in range(len(toks) - 1):
        if toks[i] == "(" and toks[i + 1] in ["then", "par-or"]:
            good_patterns += 1
    pattern_ratio = good_patterns / max(toks.count("("), 1)

    # Weighted mean
    return round(0.4 * balance + 0.3 * struct_ratio + 0.3 * pattern_ratio, 3)


def train_model(csv_path, epochs=1000, lr=2e-4, device="cuda" if torch.cuda.is_available() else "cpu"):
    dataset = SMTStrategyDataset(csv_path)
    loader = DataLoader(dataset, batch_size=6, shuffle=True, collate_fn=collate_fn)
    model = Z3Transformer().to(device)
    opt = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    loss_fn = nn.CrossEntropyLoss(ignore_index=tok2id["<PAD>"], reduction="none")

    # Track syntactic validity ratio per epoch
    def is_valid_strategy(tokens):
        try:
            grammar_parser.parse(" ".join(tokens))
            return True
        except Exception:
            return False

    for epoch in range(epochs):
        model.train()
        total_loss, valid_count, total_samples = 0, 0, 0

        # Curriculum setting: prefer shorter examples early
        dataset.epoch = epoch

        for graphs, tgts, weights in loader:
            graphs, tgts, weights = graphs.to(device), tgts.to(device), weights.to(device)
            opt.zero_grad()

            logits, class_logits = model(graphs, tgts[:-1])
            main_loss = loss_fn(
                logits.reshape(-1, logits.size(-1)),
                tgts[1:].reshape(-1)
            )
            main_loss = main_loss.mean(dim=0)

            # Grammar category supervision
            structure_tokens = ["(", ")", "then", "par-or", "using-params"]
            tactic_tokens = [
                "simplify", "solve-eqs", "propagate-values", "elim-uncnstr", "ctx-simplify",
                "card2bv", "lia2card", "qfnra-nlsat", "nla2bv", "qfnia", "smt"
            ]
            param_tokens = [p.replace(":", "") for p in PARAMS]

            cat_targets = []
            for t in tgts[1:].T:
                cats = []
                for i in t:
                    tok = id2tok.get(i.item(), "")
                    if tok in structure_tokens:
                        cats.append(0)
                    elif tok in tactic_tokens:
                        cats.append(1)
                    elif tok in param_tokens:
                        cats.append(2)
                    else:
                        cats.append(0)
                cat_targets.extend(cats)
            cat_targets = torch.tensor(cat_targets, dtype=torch.long, device=device)

            cat_loss = F.cross_entropy(class_logits.reshape(-1, 3), cat_targets, ignore_index=0)

            # Balanced parentheses penalty
            open_paren = (tgts == tok2id["("]).sum(dim=0).float()
            close_paren = (tgts == tok2id[")"]).sum(dim=0).float()
            paren_penalty = ((open_paren - close_paren).abs() / (open_paren + 1)).mean()

            weighted_loss = (main_loss * weights.mean()) + 0.8 * cat_loss + 0.05 * paren_penalty

            weighted_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()

            total_loss += weighted_loss.item()

            # Sample one decoding to check syntax validity
            if torch.rand(1).item() < 0.05:  # small fraction per batch
                seq_ids = tgts[:, 0].cpu().tolist()
                seq_toks = [id2tok[i] for i in seq_ids if i in id2tok]
                if is_valid_strategy(seq_toks):
                    valid_count += 1
                total_samples += 1
                soft_valid = soft_syntax_score(seq_toks)
                valid_count += soft_valid
                total_samples += 1
        scheduler.step()
        valid_ratio = valid_count / max(total_samples, 1)
        print(f"Epoch {epoch + 1}/{epochs} | Loss: {total_loss / len(loader):.4f} | Soft syntax: {valid_ratio:.2f}")

        # Optional checkpointing
        if (epoch + 1) % 100 == 0:
            torch.save(model.state_dict(), f"z3alpha_epoch{epoch+1}.pt")

    torch.save(model.state_dict(), "z3alpha.pt")
    return model

# =====================================================
# 8️⃣ Inference — Grammar-safe + Auto-repair
# =====================================================
import random
from lark import UnexpectedInput

def is_valid_strategy(strategy: str) -> bool:
    """
    Returns True if the strategy fully parses under the grammar.
    """
    try:
        grammar_parser.parse(strategy)
        return True
    except UnexpectedInput:
        return False
    except Exception:
        return False


def is_soft_valid(strategy: str) -> bool:
    """
    Soft validation: checks if the strategy is *almost valid* according to grammar,
    allowing minor missing parentheses or incomplete subtrees.
    """
    s = strategy.strip()
    if not s:
        return False
    if not (s.startswith("(") and "then" in s):
        return False

    opens, closes = s.count("("), s.count(")")
    if abs(opens - closes) > 3:
        return False

    try:
        grammar_parser.parse(s)
        return True
    except UnexpectedInput as e:
        msg = str(e)
        # Allow partially complete parses
        if "Unexpected end-of-input" in msg or "Expecting" in msg:
            return True
        return False
    except Exception:
        return False


def repair_strategy(strategy: str) -> str:
    """
    Repairs slightly malformed strategies to make them valid.
    - Balances parentheses
    - Adds closing ')' if missing
    - Appends a tactic if it ends with 'then'
    """
    s = strategy.strip()

    # Balance parentheses
    opens, closes = s.count("("), s.count(")")
    if opens > closes:
        s += ")" * (opens - closes)
    elif closes > opens:
        # Trim excess closing parentheses
        for _ in range(closes - opens):
            if s.endswith(")"):
                s = s[:-1]

    # Add fallback tactic if ends poorly
    if s.endswith("then"):
        s += " smt )"
    if not s.endswith(")"):
        s += ")"

    # Ensure top-level parentheses
    if not s.startswith("("):
        s = "( " + s
    return s.strip()


def repair_semantic_structure(strategy: str) -> str:
    """
    Repairs nested combinator misuse:
    - Replaces deeply nested 'then' with flat sequences
    - Removes empty groups
    - Normalizes '(then (then ...))' → '(then ...)'
    """
    # Flatten nested thens
    while "(then (then" in strategy:
        strategy = strategy.replace("(then (then", "(then")

    # Remove redundant parens
    strategy = re.sub(r"\(\s*\)", "", strategy)
    strategy = re.sub(r"\(\s*then\s*\)", "", strategy)
    strategy = re.sub(r"\(\s*par-or\s*\)", "", strategy)

    # Remove duplicate 'then'
    strategy = re.sub(r"\bthen\s+then\b", "then", strategy)

    # Ensure proper wrapping
    if not strategy.startswith("("):
        strategy = f"(then {strategy})"
    if strategy.count("(") > strategy.count(")"):
        strategy += ")" * (strategy.count("(") - strategy.count(")"))
    return strategy.strip()


import subprocess, tempfile, time, random
from lark import UnexpectedInput

# ---------- Grammar validity check ----------
def is_valid_strategy(strategy: str) -> bool:
    """Strict grammar validation via Lark parser."""
    try:
        grammar_parser.parse(strategy)
        return True
    except UnexpectedInput:
        return False
    except Exception:
        return False


# ---------- Z3 semantic validity ----------
def is_semantically_valid(strategy: str, timeout: int = 5) -> bool:
    """
    Checks if Z3 accepts the given strategy string by running a test instance.
    Returns True if Z3 executes without 'error' or 'invalid tactic' messages.
    """
    test_smt = f"""
(set-logic QF_NIA)
(declare-const x Int)
(assert (> x 0))
(check-sat-using {strategy})
"""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as tmp:
            tmp.write(test_smt)
            tmp_path = tmp.name
        result = subprocess.run(
            ["z3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out, err = result.stdout.strip(), result.stderr.strip()
        if "error" in err.lower() or "invalid" in out.lower():
            return False
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


# ---------- Runtime measurement ----------
def measure_runtime(strategy: str, timeout: int = 20) -> float:
    """
    Measures how long Z3 takes to solve a trivial instance using the strategy.
    Returns runtime in seconds (timeout if it hangs).
    """
    test_smt = f"""
(set-logic QF_NIA)
(declare-const x Int)
(assert (> x 0))
(check-sat-using {strategy})
"""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as tmp:
            tmp.write(test_smt)
            tmp_path = tmp.name

        start = time.time()
        subprocess.run(
            ["z3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        runtime = time.time() - start
        return runtime

    except subprocess.TimeoutExpired:
        return float(timeout)
    except Exception:
        return float(180)


# ---------- Core generator ----------
def generate_strategy(model, smt_path, max_len=80, device="cpu", attempts=5):
    """
    Generate syntactically and semantically valid Z3 strategies with
    strict structure control: (then <tactic> <tactic> ...).
    """
    model.eval()
    graph = smt_to_graph(smt_path)
    batch_graph = GeometricBatch.from_data_list([graph]).to(device)
    mem = model.encoder(batch_graph.x, batch_graph.edge_index, batch_graph.batch)
    mem_seq = mem.unsqueeze(0)

    best_strategy, best_runtime = None, float("inf")

    # allowed structure pattern
    PHASES = [
        ["simplify", "elim-uncnstr", "solve-eqs"],
        ["propagate-values", "ctx-simplify", "card2bv", "lia2card"],
        ["smt", "qfnia", "qfnra-nlsat"],
    ]

    for attempt in range(attempts):
        seq = ["<SOS>", "(then"]
        ids = [tok2id["<SOS>"]]
        token_history = {}
        phase = 0

        for step in range(max_len):
            tgt = torch.tensor(ids, dtype=torch.long).unsqueeze(1).to(device)
            logits, _ = model.decoder(tgt, mem_seq)
            logits = logits.clone()

            # ---------- restrict parentheses strictly ----------
            # never allow '(' except the initial "(then"
            logits[-1, 0, tok2id["("]] = -1e9

            # ---------- allow only current phase tactics ----------
            allowed_tactics = PHASES[min(phase, len(PHASES)-1)]
            mask = torch.zeros(len(VOCAB), dtype=torch.bool)
            for t in allowed_tactics + [")"]:
                if t in tok2id:
                    mask[tok2id[t]] = True
            logits[-1, 0, ~mask.to(device)] = -1e9

            # ---------- bias toward tactics ----------
            for t in allowed_tactics:
                logits[-1, 0, tok2id[t]] += 0.8

            # ---------- diversity penalty ----------
            for tok_id, count in token_history.items():
                if count > 1:
                    logits[-1, 0, tok_id] -= 1.2 * count

            probs = F.softmax(logits[-1, 0] / 1.1, dim=-1)
            topk = torch.topk(probs, k=8)
            next_id = topk.indices[torch.multinomial(topk.values, 1).item()].item()
            next_tok = id2tok[next_id]

            # record and append
            token_history[next_id] = token_history.get(next_id, 0) + 1
            ids.append(next_id)
            seq.append(next_tok)

            # advance phase when we see a late-phase tactic
            if next_tok in PHASES[min(phase, len(PHASES)-1)] and random.random() < 0.3:
                phase += 1

            # stop after solver
            if next_tok in ["smt", "qfnia", "qfnra-nlsat"]:
                break

        # close the (then …)
        strategy = " ".join(seq[1:]) + ")"
        strategy = repair_strategy(strategy)
        strategy = re.sub(r"\s+", " ", strategy)

        # validate and score
        if is_valid_strategy(strategy) and is_semantically_valid(strategy):
            runtime = measure_runtime(strategy)
            print(f"[✓] Attempt {attempt+1}: {strategy} ({runtime:.2f}s)")
            if runtime < best_runtime:
                best_strategy, best_runtime = strategy, runtime
        else:
            print(f"[x] Attempt {attempt+1} invalid or rejected: {strategy}")

    if best_strategy is None:
        raise RuntimeError("No valid strategy found.")
    print(f"\n🏁 Best valid strategy: {best_strategy}\nRuntime: {best_runtime:.2f}s")
    return best_strategy


# =====================================================
# 9️⃣ Entry
# =====================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train or infer Z3Alpha QF_NIA")
    parser.add_argument("--csv", type=str, default="output.csv")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--infer", type=str, help="Path to SMT2 file for inference")
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    if args.train:
        train_model(args.csv)
    elif args.infer:
        device = args.device
        model = Z3Transformer()
        model.load_state_dict(torch.load("z3alpha_epoch700.pt", map_location=device))
        model.to(device)
        print("🔹 Generating valid strategy...")
        strategy = generate_strategy(model, args.infer, device=device)
        print("\n✅ Final Valid Strategy:\n", strategy)
