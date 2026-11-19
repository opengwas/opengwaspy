"""ieugwaspy's usage examples, rewritten for opengwaspy.

Run with OPENGWAS_URL and OPENGWAS_TOKEN set:

    python examples/usage_examples.py

Each step prints what it found. The same steps are shown, with their output,
in the documentation's "Usage examples" page.
"""

from __future__ import annotations

import warnings

import pandas as pd

import opengwaspy as og
import opengwaspy.compat as ieugwaspy

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 12)


def main() -> dict[str, pd.DataFrame]:
    """Run every example; return the tables they make."""
    out: dict[str, pd.DataFrame] = {}

    # Exploring available studies: every analysis's metadata, one row each.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "listing all ... analyses" is expected here
        studies = og.gwasinfo()
    print(f"{len(studies):,} analyses")
    label = studies["analysis_label"].fillna("")
    bmi = studies[label.str.contains("body mass", case=False)]
    print(bmi[["id", "analysis_label", "assigned_ancestry", "sample_size"]].head())
    out["bmi"] = bmi

    # Top hits for one BMI analysis, clumped as ieugwaspy did (with settings the
    # LD stores can answer: r2=0.001 within 3,000 kb).
    study = bmi.sort_values("sample_size", ascending=False).iloc[0]["id"]
    leads = ieugwaspy.tophits([study], r2=0.001, kb=3000)
    print(f"{study}: {len(leads)} independent hits")
    print(leads[["rsid", "chr", "position", "ea", "beta", "p"]].sort_values("p").head())
    out["leads"] = leads

    # Associations of three SNPs in three analyses, with LD proxies.
    snps = list(leads.sort_values("p")["rsid"].dropna().head(3))
    others = list(bmi["id"].head(3))
    assocs = ieugwaspy.associations(snps, others, proxies=1, r2=0.8, align_alleles=1)
    print(assocs[["id", "rsid", "ea", "nea", "beta", "p", "proxy"]])
    out["assocs"] = assocs

    # A PheWAS of the strongest BMI hit: every association with p <= 1e-5.
    phewas = ieugwaspy.phewas([snps[0]], pval=1e-5)
    print(phewas.sort_values("p")[["trait", "beta", "p", "n"]].head())
    out["phewas"] = phewas

    # chr:pos to rsID (ranges are left as they are).
    print(ieugwaspy.variants_to_rsid(["19:44908684", "7:105561135-105563135"]))
    return out


if __name__ == "__main__":
    og.configure()
    main()
