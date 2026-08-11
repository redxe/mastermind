# Quantum Algorithm Engineering paper

This repository uses a document-oriented MVC architecture: scientific content and references are the **model**, typography is the **view**, and the root composition file is the **controller**. The names remain conventional for LaTeX so the project is understandable to both software engineers and paper authors.

## Architecture

```text
.
├── main.tex                              # Controller / composition root
├── quantum_algorithm_engineering.tex     # Backward-compatible entry point
├── build.ps1                             # Windows build interface
├── .latexmkrc                            # Reproducible build configuration
├── references/
│   └── quantum_algorithm_engineering.bib # Citation data
└── src/
    ├── content/                          # Model
    │   ├── metadata.tex                  # Title, author, keywords, central claim
    │   ├── frontmatter/                  # Title page and abstract
    │   ├── sections/                     # Numbered argument modules
    │   └── appendices/                   # Reusable worksheets and reporting rules
    └── presentation/                     # View
        ├── packages.tex                  # Package dependencies
        ├── commands.tex                  # Shared semantic/math commands
        └── theme.tex                     # Layout, color, headings, and callouts
```

The numbered section files preserve the paper's execution order. The four phases in `main.tex` make the reasoning pipeline explicit:

1. **Problem contract and opportunity** — define the output, baseline, and quantum mechanism.
2. **Complete experiment engineering** — calculate resources, validation, and the hybrid boundary.
3. **Application stress tests** — test the framework against concrete domains.
4. **Synthesis and reusable workflow** — turn conclusions into review questions and reporting rules.

## Build

On Windows (works without changing PowerShell execution policy):

```text
build.cmd
```

The PDF and all generated files are written to `build/`; the primary output is `build/main.pdf`.

Cross-platform or direct build:

```text
latexmk -pdf main.tex
```

Clean generated files on Windows:

```text
build.cmd clean
```

An equivalent `build.ps1` interface is also available where local PowerShell policy permits scripts.

`latexmk` runs LaTeX and BibTeX as many times as needed, so citations and cross-references resolve even though the source and bibliography are separated.

## Change routing

| Problem or change | Start here |
|---|---|
| Argument, claim, equation, table, or domain example | Matching numbered file under `src/content/sections/` |
| Document order or phase boundaries | `main.tex` |
| Title, author, date, keywords, or central claim | `src/content/metadata.tex` |
| Abstract or title-page wording | `src/content/frontmatter/` |
| Citation metadata or source URL | `references/quantum_algorithm_engineering.bib` |
| Repeated notation or a semantic macro | `src/presentation/commands.tex` |
| Colors, margins, headers, heading styles, or callouts | `src/presentation/theme.tex` |
| Missing or conflicting LaTeX package | `src/presentation/packages.tex` |
| Build artifacts appearing beside source files | `.latexmkrc` and `.gitignore` |

## Structured authoring workflow

When adding or revising a research claim, route it through the paper in this order:

1. **Contract:** required observable, scale, error, confidence, deadline, and verification path.
2. **Classical obstruction:** strongest matched baseline and measured bottleneck.
3. **Quantum mechanism:** named structure, primitive, access model, and compact output.
4. **Physical ledger:** compiled depth, shots or logical resources, latency, and total error.
5. **Evidence:** exact controls, mechanism-off controls, application cases, stress cases, and crossover tests.
6. **Decision:** continue, repartition the hybrid workflow, or reject the quantum approach.

For a new section, create the next numbered file under `src/content/sections/`, add one `\input{...}` line in `main.tex`, keep labels globally unique, add any citations to the bibliography, and run the build. Every included source file contains a `% !TeX root` directive so it can be edited from VS Code while still compiling through `main.tex`.
