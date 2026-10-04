"""Terminal helper for hand-labeling the golden 50. Standard library only; makes no model or network calls.

The helper never suggests a label: every value in the output comes from the person typing. Star ratings and
other metadata are hidden so labels are based on the review text alone, as the grading contract requires.

Usage:
    python3 evals/label_golden.py            # label (resumes where you left off)
    python3 evals/label_golden.py --list     # show progress
    python3 evals/label_golden.py --redo 7   # relabel review #7
    python3 evals/label_golden.py --check    # validate the saved file
"""

import argparse
import csv
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO.parent / "Final Assignment - Spotify Reviews Dataset" / "golden_50_to_label.csv"
DEFAULT_OUTPUT = REPO / "evals" / "golden" / "golden_50_human_labels.csv"

TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")  # official precedence order
SOURCE_FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
LABEL_FIELDS = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review")
EXTRA_FIELDS = ("ambiguous", "alt_topics", "alt_intents", "alt_severities", "notes", "labeled_at")
OUT_FIELDS = SOURCE_FIELDS + LABEL_FIELDS + EXTRA_FIELDS

RULES = """\
TOPIC   1 access  2 usability  3 playback  4 downloads  5 catalog  6 billing  7 support  8 other
        highest supported severity wins; tie -> first mentioned. Praise -> first SPECIFIC feature (general = other).
        Paid-plan mention alone is not billing; premium-only controls and paywalls ARE billing.
INTENT  1 cancellation > 2 complaint > 3 request > 4 praise > 5 unclear   (mixed praise+criticism = complaint)
        bare boycott slogan = unclear; "bad app" = complaint, don't infer a defect.
SEVER.  1 no problem/praise/request  2 annoyance, no functional loss  3 restricted/degraded, some use remains
        4 core task blocked  5 explicit SERIOUS financial, privacy or data harm.  Cancellation doesn't raise it.
        Support: 2 only annoyed, 3 problem unresolved, 4 blocked.  Paywalled feature = 3.
SENTI.  -1 very neg   -0.5 neg   0 neutral/mixed   0.5 pos   1 very pos"""

HELP = "At any prompt: q = quit (this review is not saved), ? = show rules again."


class Quit(Exception):
    pass


def load_input(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, strict=True))
    if len(rows) != 50 or len({r["review_id"] for r in rows}) != 50:
        sys.exit(f"Expected 50 unique reviews in {path}, found {len(rows)}")
    return rows


def load_output(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["review_id"]: r for r in csv.DictReader(f, strict=True)}


def save_output(path, source_rows, labels):
    """Write the whole file to a temp file, then atomically replace, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        for src in source_rows:
            if src["review_id"] in labels:
                writer.writerow(labels[src["review_id"]])
    os.replace(tmp, path)


def ask(prompt, parse, allow_blank=False):
    while True:
        raw = input(prompt).strip()
        if raw == "q":
            raise Quit
        if raw == "?":
            print(RULES)
            continue
        if raw == "" and allow_blank:
            return ""
        try:
            return parse(raw)
        except ValueError as e:
            print(f"   ! {e}")


def choice(options):
    def parse(raw):
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        raise ValueError("enter a number 1-%d or one of: %s" % (len(options), ", ".join(options)))
    return parse


def severity(raw):
    if raw in {"1", "2", "3", "4", "5"}:
        return raw
    raise ValueError("enter a whole number 1-5")


def sentiment(raw):
    value = float(raw)  # raises ValueError on junk
    if not -1 <= value <= 1:
        raise ValueError("must be between -1 and 1")
    return raw


def yes_no(raw):
    if raw.lower() in {"y", "yes"}:
        return "true"
    if raw.lower() in {"n", "no"}:
        return "false"
    raise ValueError("enter y or n")


def multi(options):
    def parse(raw):
        values = [choice(options)(x.strip()) for x in raw.split(",") if x.strip()]
        return ",".join(values)
    return parse


def label_one(number, src):
    print("\n" + "=" * 100)
    print(f"Review #{number} of 50   id {src['review_id']}")
    print("-" * 100)
    print(src["review_text"] if src["review_text"] else "(empty text)")
    print("-" * 100)
    text = src["review_text"]

    def quote(raw):
        if raw == "=":
            return text
        if not raw:
            raise ValueError("a quote is required")
        if raw not in text:
            raise ValueError("not an exact substring of the review (check spelling, spaces, punctuation)")
        return raw

    row = {k: src[k] for k in SOURCE_FIELDS}
    row["topic"] = ask("topic (1-8): ", choice(TOPICS))
    row["intent"] = ask("intent (1-5): ", choice(INTENTS))
    row["severity"] = ask("severity (1-5): ", severity)
    row["sentiment"] = ask("sentiment (-1 to 1): ", sentiment)
    row["evidence_quote"] = ask("evidence quote (paste exact text, or = for the whole review): ", quote)
    row["entities"] = ask("entities, comma-separated (Enter for none): ", lambda r: r, allow_blank=True)
    row["needs_review"] = ask("needs_review? (y/n): ", yes_no)
    row["ambiguous"] = ask("ambiguous - another label would also be defensible? (y/n): ", yes_no)
    row["alt_topics"] = row["alt_intents"] = row["alt_severities"] = ""
    if row["ambiguous"] == "true":
        print("   Other acceptable labels (comma-separated numbers or names; Enter to skip a field):")
        row["alt_topics"] = ask("   also-acceptable topics: ", multi(TOPICS), allow_blank=True)
        row["alt_intents"] = ask("   also-acceptable intents: ", multi(INTENTS), allow_blank=True)
        row["alt_severities"] = ask("   also-acceptable severities: ",
                                    lambda r: ",".join(severity(x.strip()) for x in r.split(",") if x.strip()),
                                    allow_blank=True)
    row["notes"] = ask("notes (optional, Enter to skip): ", lambda r: r, allow_blank=True)
    row["labeled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"\n   -> {row['topic']} / {row['intent']} / severity {row['severity']} / sentiment {row['sentiment']}"
          f" / needs_review {row['needs_review']} / ambiguous {row['ambiguous']}")
    print(f"   -> quote: {row['evidence_quote']!r}")
    if ask("save this? (y = save, n = redo this review): ", yes_no) == "false":
        return label_one(number, src)
    return row


def check(source_rows, labels):
    problems = []
    for i, src in enumerate(source_rows, 1):
        row = labels.get(src["review_id"])
        if not row:
            problems.append(f"#{i}: not labeled yet")
            continue
        if any(row[k] != src[k] for k in SOURCE_FIELDS):
            problems.append(f"#{i}: source fields differ from the input file")
        if row["topic"] not in TOPICS or row["intent"] not in INTENTS or row["severity"] not in "12345":
            problems.append(f"#{i}: invalid topic/intent/severity")
        try:
            sentiment(row["sentiment"])
        except ValueError:
            problems.append(f"#{i}: invalid sentiment")
        if not row["evidence_quote"] or row["evidence_quote"] not in src["review_text"]:
            problems.append(f"#{i}: evidence quote is not an exact substring")
        if row["needs_review"] not in {"true", "false"} or row["ambiguous"] not in {"true", "false"}:
            problems.append(f"#{i}: needs_review/ambiguous must be true or false")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="show progress and saved labels")
    group.add_argument("--redo", type=int, metavar="N", help="relabel review number N (1-50)")
    group.add_argument("--check", action="store_true", help="validate the saved labels file")
    args = parser.parse_args()

    source_rows = load_input(args.input)
    labels = load_output(args.output)

    if args.list:
        for i, src in enumerate(source_rows, 1):
            row = labels.get(src["review_id"])
            status = (f"{row['topic']:<10} {row['intent']:<13} sev {row['severity']}  sent {row['sentiment']:>5}"
                      f"  {'AMBIG' if row['ambiguous'] == 'true' else ''}") if row else "-- not labeled --"
            print(f"#{i:>2}  {status}")
        print(f"\n{len(labels)} of 50 labeled  ->  {args.output}")
        return

    if args.check:
        problems = check(source_rows, labels)
        print("\n".join(problems) if problems else "All 50 labels present and valid.")
        sys.exit(1 if problems else 0)

    if args.redo is not None:
        if not 1 <= args.redo <= 50:
            sys.exit("--redo takes a review number from 1 to 50")
        todo = [(args.redo, source_rows[args.redo - 1])]
    else:
        todo = [(i, s) for i, s in enumerate(source_rows, 1) if s["review_id"] not in labels]

    print(RULES + "\n\n" + HELP)
    print(f"{len(labels)} of 50 already labeled; {len(todo)} to go. Saves after every review.")
    try:
        for number, src in todo:
            labels[src["review_id"]] = label_one(number, src)
            save_output(args.output, source_rows, labels)
            print(f"   saved ({len(labels)} of 50)")
    except (Quit, EOFError, KeyboardInterrupt):
        print(f"\nStopped. {len(labels)} of 50 saved in {args.output}. Run again to resume.")
        return
    print("\nDone with this session. Run with --check to validate.")


if __name__ == "__main__":
    main()
