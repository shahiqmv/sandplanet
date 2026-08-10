"""Render Planet_User_Guide.html -> Planet_User_Guide_R2.pdf with WeasyPrint
(the same engine Planet uses for its own document PDFs).

    ../backend/.venv/Scripts/python.exe build_guide.py

Relative image paths (assets/, screenshots/) resolve against this folder.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "Planet_User_Guide.html"
OUT = HERE / "Planet_User_Guide_R2.pdf"


def main():
    from weasyprint import HTML

    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    HTML(filename=str(SRC), base_url=str(HERE)).write_pdf(str(OUT))
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.name}  ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
