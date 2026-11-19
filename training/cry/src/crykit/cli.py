"""crykit command line. Run `uv run crykit --help`."""

import argparse
import shutil
import tempfile
from pathlib import Path

SMOKE_LIMIT = 24  # clips per ICSD split in --smoke runs


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="crykit", description="Train and export the Frecklebubby cry models.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name, help_, *args):
        p = sub.add_parser(name, help=help_)
        for a in args:
            {"icsd": lambda: p.add_argument("--icsd", type=Path, required=True, help="ICSD root (has audio/ and metadata/)"),
             "reason": lambda: p.add_argument("--reason-data", type=Path, required=True, help="DeepInfant Data/v2 folder"),
             "work": lambda: p.add_argument("--work", type=Path, required=True, help="work folder (embeddings, checkpoints)"),
             "out": lambda: p.add_argument("--out", type=Path, required=True, help="folder for the exported files"),
             "smoke": lambda: p.add_argument("--smoke", action="store_true", help=f"tiny run: {SMOKE_LIMIT} clips per split"),
             }[a]()
        return p

    cmd("compare-encoders", "linear-probe comparison of candidate encoders on an ICSD subset", "icsd", "work")
    cmd("prepare", "check the data and write the reason label-cleaning log", "icsd", "reason", "work")
    cmd("embed", "cache frozen encoder embeddings (ICSD and reason clips)", "icsd", "reason", "work", "smoke")
    p = cmd("train-detector", "train the cry/snore detector head", "icsd", "work", "smoke")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--unfreeze", action="store_true", help="fine-tune the encoder too (reads audio; use a GPU)")
    p.add_argument("--device", default="cpu", help="cpu or cuda")
    cmd("train-reason", "evaluate (grouped CV) and fit the reason model", "work")
    cmd("export", "write cry_detector.onnx, cry_reason.onnx, model_card.json", "work", "out")
    p = cmd("all", "prepare, embed, train-detector, train-reason, export", "icsd", "reason", "work", "out", "smoke")
    p.add_argument("--epochs", type=int, default=40)
    a = ap.parse_args(argv)

    if a.cmd == "compare-encoders":
        from .compare import run

        run(a.icsd, a.work, ["mn10_as", "mispeech/ced-tiny", "ntu-spml/distilhubert"])
    elif a.cmd == "prepare":
        prepare(a.icsd, a.reason_data, a.work)
    elif a.cmd == "embed":
        embed(a.icsd, a.reason_data, a.work, a.smoke)
    elif a.cmd == "train-detector":
        from .detector import train

        train(a.icsd, a.work, a.work, epochs=2 if a.smoke else a.epochs, unfreeze=a.unfreeze,
              limit=SMOKE_LIMIT if a.smoke else None, device=a.device)
    elif a.cmd == "train-reason":
        from .reason import evaluate

        evaluate(a.work, a.work)
    elif a.cmd == "export":
        from .export import export

        export(a.work, a.out)
    elif a.cmd == "all":
        run_all(a.icsd, a.reason_data, a.work, a.out, a.smoke, a.epochs)


def prepare(icsd: Path, reason_data: Path, work: Path) -> None:
    from .data import ICSD_SPLITS, clean_reason_labels, icsd_index

    work.mkdir(parents=True, exist_ok=True)
    for split in ICSD_SPLITS:
        items = icsd_index(icsd, split)
        missing = [it["name"] for it in items if not it["path"].is_file()]
        print(f"{split}: {len(items)} clips, {len(missing)} missing")
    rows, log = clean_reason_labels(reason_data)
    (work / "reason_cleaning.log").write_text("\n".join(log) + "\n")
    print(log[-1])


def embed(icsd: Path, reason_data: Path, work: Path, smoke: bool) -> None:
    from .embed import embed_icsd, embed_reason

    embed_icsd(icsd, work, SMOKE_LIMIT if smoke else None)
    embed_reason(reason_data, work, 12 if smoke else None)


def run_all(icsd: Path, reason_data: Path, work: Path, out: Path, smoke: bool, epochs: int) -> None:
    from .detector import train
    from .export import export
    from .reason import evaluate

    if smoke:  # never mix smoke files with a real run
        work = Path(tempfile.mkdtemp(prefix="crykit-smoke-"))
    prepare(icsd, reason_data, work)
    embed(icsd, reason_data, work, smoke)
    train(icsd, work, work, epochs=2 if smoke else epochs, limit=SMOKE_LIMIT if smoke else None)
    evaluate(work, work, folds=3 if smoke else 5, repeats=1 if smoke else 5)
    export(work, out)
    if smoke:
        shutil.rmtree(work)
