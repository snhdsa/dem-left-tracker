#!/usr/bin/env python3
"""
Recursive PDF to Markdown Extraction Comparison

This script processes all PDF files in a directory (and subdirectories),
comparing PyPDF and pymupdf libraries for text/markdown extraction.

"""

import argparse
import csv
import re
import sys
import time
import warnings
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf4llm
from pypdf import PdfReader

warnings.filterwarnings("ignore", category=UserWarning)


# ------------------------------------------------------------------------------
# Extraction Functions
# ------------------------------------------------------------------------------
def extract_text_pypdf(pdf_path: str, use_layout_mode: bool = True) -> str:
    try:
        reader = PdfReader(pdf_path)
        text_parts = []
        for page in reader.pages:
            if use_layout_mode:
                page_text = page.extract_text(extraction_mode="layout")
            else:
                page_text = page.extract_text()
            text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Error extracting text with PyPDF from {pdf_path}: {e}")
        return ""


def extract_markdown_pymupdf(pdf_path: str) -> str:
    try:
        # The core function call is incredibly simple
        md_text = pymupdf4llm.to_markdown(pdf_path)
        return md_text
    except Exception as e:
        print(f"Error extracting markdown with pymupdf4llm from {pdf_path}: {e}")
        return ""


# ------------------------------------------------------------------------------
# Analysis Functions
# ------------------------------------------------------------------------------


def calculate_similarity(text1: str, text2: str) -> float:
    norm1 = re.sub(r"\s+", " ", text1).strip()
    norm2 = re.sub(r"\s+", " ", text2).strip()
    return SequenceMatcher(None, norm1, norm2).ratio()


def analyze_headers(text: str, markdown_text: str) -> dict:
    plain_headers = re.findall(r"^\s*([A-Z][A-Z\s]{3,})$", text, re.MULTILINE)
    md_headers = re.findall(r"^#{1,6}\s+(.+)$", markdown_text, re.MULTILINE)
    return {
        "plain_headers_count": len(plain_headers),
        "markdown_headers_count": len(md_headers),
        "plain_headers_sample": plain_headers[:3],
        "markdown_headers_sample": md_headers[:3],
    }


def analyze_tables(markdown_text: str) -> int:
    table_pattern = r"^\|.+\|$\n^\|[-:\s]+\|$\n(?:^\|.+\|$\n?)+"
    tables = re.findall(table_pattern, markdown_text, re.MULTILINE)
    return len(tables)


# ------------------------------------------------------------------------------
# Single File Processing
# ------------------------------------------------------------------------------


def process_single_pdf(pdf_path: Path, pypdf_layout: bool) -> dict:
    """Process one PDF and return metrics."""
    print(f"\n📄 Processing: {pdf_path}")

    # PyPDF
    start = time.time()
    pypdf_out = extract_text_pypdf(str(pdf_path), use_layout_mode=pypdf_layout)
    pypdf_time = time.time() - start

    # pymupdf
    start = time.time()
    pymupdf_out = extract_markdown_pymupdf(str(pdf_path))
    pymupdf_time = time.time() - start

    similarity = calculate_similarity(pypdf_out, pymupdf_out)
    header_analysis = analyze_headers(pypdf_out, pymupdf_out)
    tables = analyze_tables(pymupdf_out)

    return {
        "file": str(pdf_path),
        "pypdf_time": round(pypdf_time, 4),
        "pymupdf_time": round(pymupdf_time, 4),
        "pypdf_chars": len(pypdf_out),
        "pymupdf_chars": len(pymupdf_out),
        "similarity": round(similarity, 4),
        "plain_headers": header_analysis["plain_headers_count"],
        "markdown_headers": header_analysis["markdown_headers_count"],
        "tables_detected": tables,
        "pypdf_output": pypdf_out,  # for optional saving
        "pymupdf_output": pymupdf_out,
    }


# ------------------------------------------------------------------------------
# Main Recursive Processing
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Recursively compare PDF extraction across all PDFs in a directory"
    )
    parser.add_argument(
        "directory", help="Root directory containing PDF files (searched recursively)"
    )
    parser.add_argument(
        "--output-dir",
        default="./comparison_outputs",
        help="Directory to save CSV report and extracted files",
    )
    parser.add_argument(
        "--pypdf-layout",
        action="store_true",
        default=True,
        help="Use layout mode in PyPDF",
    )
    parser.add_argument(
        "--no-pypdf-layout",
        action="store_false",
        dest="pypdf_layout",
        help="Disable layout mode in PyPDF",
    )
    parser.add_argument(
        "--save-outputs",
        action="store_true",
        help="Save extracted text/markdown for each PDF",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of PDFs to process (for testing)",
    )

    args = parser.parse_args()

    root_dir = Path(args.directory)
    if not root_dir.exists():
        print(f"❌ Directory not found: {root_dir}")
        sys.exit(1)

    # Find all PDF files recursively
    pdf_files = list(root_dir.rglob("*.pdf")) + list(root_dir.rglob("*.PDF"))
    pdf_files = sorted(set(pdf_files))  # remove duplicates from case‑insensitive glob

    if not pdf_files:
        print(f"⚠️  No PDF files found in {root_dir}")
        return

    if args.max_files:
        pdf_files = pdf_files[: args.max_files]

    print(f"🚀 Found {len(pdf_files)} PDF file(s). Processing...")

    # Prepare output directory
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}]")
        try:
            result = process_single_pdf(pdf_path, args.pypdf_layout)
            results.append(result)

            # Optionally save the extracted outputs
            if args.save_outputs:
                pdf_name = pdf_path.stem
                file_out_dir = output_path / pdf_path.parent.relative_to(root_dir)
                file_out_dir.mkdir(parents=True, exist_ok=True)

                # Save PyPDF output
                (file_out_dir / f"{pdf_name}_pypdf.txt").write_text(
                    result["pypdf_output"], encoding="utf-8"
                )
                # Save pymupdf output
                (file_out_dir / f"{pdf_name}_pymupdf.md").write_text(
                    result["pymupdf_output"], encoding="utf-8"
                )

            # Print brief summary for this file
            print(
                f"   ✅ Similarity: {result['similarity']:.4f}  |  "
                f"PyPDF: {result['pypdf_time']}s  |  "
                f"pymupdf: {result['pymupdf_time']}s"
            )

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            results.append(
                {
                    "file": str(pdf_path),
                    "error": str(e),
                    **{k: None for k in ["pypdf_time", "pymupdf_time", "similarity"]},
                }
            )

    # --------------------------------------------------------------------------
    # Generate CSV Report
    # --------------------------------------------------------------------------
    csv_path = output_path / "comparison_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "file",
            "pypdf_time",
            "pymupdf_time",
            "pypdf_chars",
            "pymupdf_chars",
            "similarity",
            "plain_headers",
            "markdown_headers",
            "tables_detected",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k) for k in fieldnames}
            writer.writerow(row)

    print(f"\n📊 CSV report saved to: {csv_path}")

    # Also print aggregate statistics
    valid = [r for r in results if r.get("similarity") is not None]
    if valid:
        avg_sim = sum(r["similarity"] for r in valid) / len(valid)
        print(f"\n📈 Average similarity across {len(valid)} files: {avg_sim:.4f}")

    print("\n✨ All done!")


if __name__ == "__main__":
    main()
