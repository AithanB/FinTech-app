"""Explicit CSV conversions; JSON remains strict. No public loader reads truth."""

import csv
import re
from pathlib import Path
from typing import TypeVar

from .schemas import FXRow, Invoice, LedgerRow, Manifest, Payment, Policy, PublicEpisode, StrictModel

Model = TypeVar("Model", bound=StrictModel)
CSV_NULL = "null"


def read_json(path: Path, model: type[Model]) -> Model:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: StrictModel) -> None:
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")


def read_jsonl(path: Path, model: type[Model]) -> list[Model]:
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl(path: Path, rows: list[StrictModel]) -> None:
    path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8", newline="\n")


def read_csv(path: Path, model: type[LedgerRow] | type[FXRow]):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(model.model_fields):
            raise ValueError("CSV columns must exactly match the published schema order")
        result = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("malformed CSV row")
            if model is LedgerRow:
                for key in ("invoice_id", "payment_id"):
                    if row[key] == CSV_NULL:
                        row[key] = None
                for key in ("debit_minor", "credit_minor", "posting_sequence"):
                    if re.fullmatch(r"0|[1-9][0-9]*", row[key]) is None:
                        raise ValueError("CSV integer must be unsigned decimal digits")
                    row[key] = int(row[key])
            result.append(model.model_validate(row))
        return result


def write_csv(path: Path, rows, model: type[LedgerRow] | type[FXRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(model.model_fields), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            data = row.model_dump(mode="json")
            if model is LedgerRow:
                for key in ("invoice_id", "payment_id"):
                    if data[key] == CSV_NULL:
                        raise ValueError("reserved CSV null token cannot be an ID")
            writer.writerow({key: CSV_NULL if value is None else value for key, value in data.items()})


def load_public(directory: Path) -> PublicEpisode:
    return PublicEpisode(
        manifest=read_json(directory / "manifest.json", Manifest),
        policy=read_json(directory / "policy.json", Policy),
        ledger=read_csv(directory / "ledger.csv", LedgerRow),
        invoices=read_jsonl(directory / "invoices.jsonl", Invoice),
        payments=read_jsonl(directory / "payments.jsonl", Payment),
        fx=read_csv(directory / "fx.csv", FXRow),
    )


def save_public(directory: Path, episode: PublicEpisode) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "manifest.json", episode.manifest)
    write_json(directory / "policy.json", episode.policy)
    write_csv(directory / "ledger.csv", episode.ledger, LedgerRow)
    write_csv(directory / "fx.csv", episode.fx, FXRow)
    write_jsonl(directory / "invoices.jsonl", episode.invoices)
    write_jsonl(directory / "payments.jsonl", episode.payments)
