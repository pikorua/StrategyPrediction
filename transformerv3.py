"""
Z3Alpha v4 — Unified Tactic+Param Transformer
---------------------------------------------
This version treats each tactic or (tactic,param,value) triple as a single token.

Example tokens:
  simplify
  smt_random_seed_200
  simplify_elim_and_false

Training input: CSV with (smt_path, strategy, runtime)
"""

import os, re, csv, torch, argparse
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

# ============================================================
# 1️⃣ Vocabulary Builder — Unified Tokens
# ============================================================

def build_unified_vocab(csv_path):
    """
    Extracts unique tactic tokens and (tactic,param,value) combos.
    Returns tok2id, id2tok, and prints debug examples.
    """
    tactic_pattern = re.compile(r"\b[a-zA-Z0-9_\-]+\b")
    param_combo_pattern = re.compile(r"\(using-params\s+(\w+)\s+:([\w_\-]+)\s+([\w\d]+)\)")

    base_tokens = ["<PAD>", "<SOS>", "<EOS>", "<UNK>"]
    vocab = set()

    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            strat = row[1]

            # Plain tactics
            for t in tactic_pattern.findall(strat):
                if t not in ["then", "par-or", "using", "params"]:
                    vocab.add(t.lower())

            # Combined param-tactic tokens
            for m in param_combo_pattern.findall(strat):
                tactic, param, val = m
                vocab.add(f"{tactic.lower()}_{param.lower()}_{val.lower()}")

    vocab = base_tokens + sorted(vocab)
    tok2id = {t: i for i, t in enumerate(vocab)}
    id2tok = {i: t for t, i in tok2id.items()}

    print(f"🧩 Built unified vocab of {len(vocab)} tokens.")
    print("🔹 Example tokens:", list(vocab[0:25]))
    return tok2id, id2tok


# ============================================================
# 2️⃣ Tokenizer
# ============================================================

def tokenize_unified(strategy, tok2id):
    """
    Converts a strategy string into unified token IDs.
    """
    ids = []
    param_combo_pattern = re.compile(r"\(using-params\s+(\w+)\s+:([\w_\-]+)\s+([\w\d]+)\)")

    # Replace parameter combos first
    for m in param_combo_pattern.findall(strategy):
        tactic, param, val = m
        combo = f"{tactic.lower()}_{param.lower()}_{val.lower()}"
        strategy = strategy.replace(f"(using-params {tactic} :{param} {val})", combo)

    # Split by whitespace
    for tok in strategy.split():
        tok = tok.strip().lower()
        if not tok or tok in ["then", "par-or", "(", ")"]:
            continue
        ids.append(tok2id.get(tok, tok2id["<UNK>"]))
    return [tok2id["<SOS>"]] + ids + [tok2id["<EOS>"]]


# ============================================================
# 3️⃣ Feature Extractor
# ============================================================

def simple_feature_extractor(smt_path):
    with open(smt_path) as f:
        content = f.read()
    num_asserts = len(re.findall(r"\(assert", content))
    num_vars = len(re.findall(r"\(declare", content))
    num_ops = len(re.findall(r"[+\-*<>=]", content))
    avg_line_len = sum(map(len, content.splitlines())) / max(1, len(content.splitlines()))
    feats = torch.tensor([num_asserts, num_vars, num_ops, avg_line_len], dtype=torch.float32)
    return F.normalize(feats, dim=0)


# ============================================================
# 4️⃣ Dataset
# ============================================================

class SMTStrategyDataset(Dataset):
    def __init__(self, csv_path, tok2id, feature_extractor=simple_feature_extractor):
        self.data, self.tok2id, self.feature_extractor = [], tok2id, feature_extractor
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
        feats = self.feature_extractor(smt_path)
        token_ids = tokenize_unified(strategy, self.tok2id)
        seq = torch.tensor(token_ids, dtype=torch.long)
        weight = torch.tensor(1.0 / (runtime + 1e-3), dtype=torch.float32)
        return feats, seq, weight


def collate_fn(batch):
    feats, seqs, weights = zip(*batch)
    feats = torch.stack(feats)
    max_len = max(len(s) for s in seqs)
    padded = torch.full((max_len, len(seqs)), fill_value=0, dtype=torch.long)
    for i, s in enumerate(seqs):
        padded[:len(s), i] = s
    weights = torch.stack(weights)
    return feats, padded, weights


# ============================================================
# 5️⃣ Model — MLP Encoder + Transformer Decoder
# ============================================================

class Z3TransformerV4(nn.Module):
    def __init__(self, input_dim, vocab_size, hidden=256, n_layers=4, n_heads=8):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
        )
        self.embed = nn.Embedding(vocab_size, hidden)
        dec_layer = nn.TransformerDecoderLayer(
            d_model=hidden, nhead=n_heads, dim_feedforward=hidden*4,
            dropout=0.1, activation="gelu"
        )
        self.decoder = nn.TransformerDecoder(dec_layer, num_layers=n_layers)
        self.out = nn.Linear(hidden, vocab_size)

    def forward(self, feats, tgt):
        mem = self.encoder(feats).unsqueeze(0)  # [1, batch, hidden]
        tgt_emb = self.embed(tgt)
        mask = nn.Transformer.generate_square_subsequent_mask(tgt.size(0)).to(tgt.device)
        out = self.decoder(tgt_emb, mem, tgt_mask=mask)
        return self.out(out)


# ============================================================
# 6️⃣ Training
# ============================================================

# ============================================================
# 🧠 Training — Tactics-only version
# ============================================================

def train_model(csv_path, epochs=50, lr=2e-4, device="cuda" if torch.cuda.is_available() else "cpu"):
    tok2id, id2tok = build_unified_vocab(csv_path)  # still builds from tactics only
    vocab_size = len(tok2id)

    dataset = SMTStrategyDataset(csv_path, tok2id)
    loader = DataLoader(dataset, batch_size=8, shuffle=True, collate_fn=collate_fn)

    model = Z3TransformerV4(input_dim=4, vocab_size=vocab_size).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)

    # Simpler loss: pure token-level cross-entropy
    loss_fn = nn.CrossEntropyLoss(ignore_index=tok2id["<PAD>"])

    print(f"[INFO] Training tactics-only transformer with {vocab_size} tokens.")

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        total_tokens = 0

        for feats, seqs, _ in loader:
            feats, seqs = feats.to(device), seqs.to(device)
            optimizer.zero_grad()

            logits = model(feats, seqs[:-1])  # teacher forcing
            loss = loss_fn(
                logits.reshape(-1, vocab_size),
                seqs[1:].reshape(-1)
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item() * seqs.size(1)
            total_tokens += seqs.size(1)

        avg_loss = total_loss / max(1, total_tokens)
        print(f"Epoch {epoch+1}/{epochs} | Avg token loss: {avg_loss:.4f}")

    torch.save({
        "model": model.state_dict(),
        "tok2id": tok2id,
        "id2tok": id2tok
    }, "z3alpha_v3.pt")

    print("✅ Training complete — model saved as z3alpha_v3.pt")

# ============================================================
# 7️⃣ Inference
# ============================================================

def generate_strategy(model, smt_path, feature_extractor, tok2id, id2tok, max_len=40, device="cpu"):
    model.eval()
    feats = feature_extractor(smt_path).unsqueeze(0).to(device)
    seq = [tok2id["<SOS>"]]
    for _ in range(max_len):
        tgt = torch.tensor(seq, dtype=torch.long).unsqueeze(1).to(device)
        logits = model(feats, tgt)
        next_id = logits[-1, 0].argmax().item()
        if next_id == tok2id["<EOS>"]:
            break
        seq.append(next_id)
    tokens = [id2tok[i] for i in seq[1:] if id2tok[i] not in ("<UNK>", "<PAD>", "<EOS>")]
    print("🔹 Generated tokens:", tokens[:15])
    return "(then " + " ".join(tokens) + ")"


# ============================================================
# 8️⃣ Entry
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Z3Alpha v4 — Unified Tactic+Param Transformer")
    parser.add_argument("--csv", type=str, required=True)
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--infer", type=str, help="Path to SMT2 file for inference")
    args = parser.parse_args()

    if args.train:
        train_model(args.csv)
    elif args.infer:
        ckpt = torch.load("z3alpha_v3.pt", map_location="cpu")
        tok2id, id2tok = ckpt["tok2id"], ckpt["id2tok"]
        model = Z3TransformerV4(input_dim=4, vocab_size=len(tok2id))
        model.load_state_dict(ckpt["model"])
        strat = generate_strategy(model, args.infer, simple_feature_extractor, tok2id, id2tok)
        print("\nPredicted strategy:\n", strat)
