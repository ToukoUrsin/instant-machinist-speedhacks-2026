# The problem: every new part waits for a CNC programmer

A build-to-print job shop gets a drawing and a STEP model, quotes it, and makes the part. Before the
first chip, someone has to read the drawing, plan setups, pick tools, write toolpaths, post G-code and
check it. In a high-mix shop that happens for every new order, and it is done by the same few senior
people who also quote and run the machines.

## Who has this problem

| Fact | Number | Source |
|---|---|---|
| US machine shops (NAICS 332710) | **16,876**; 83 % have fewer than 20 people, 95 % fewer than 50 | 2022 Economic Census, cited in a16z, [*The Case for the American Manufacturing Asset Class*](https://a16z.com/the-case-for-the-american-manufacturing-asset-class/) (Oct 2026); cross-checked against [Census table ECNSIZE2022](https://data.census.gov/table/ECNSIZE2022.EC2200SIZEEMPFIRM) |
| Programming one new part by hand | typically **1–4 hours**: about 1 h for a simple 3-axis part, 1–2 h in another shop, 4–8 h for a complex one; **weeks** for the most complex |  [CloudNC, 2023](https://www.cloudnc.com/blog/cam-assist-beta-feedback); [Modern Machine Shop, 2024](https://www.mmsonline.com/articles/automating-part-programming-cuts-the-time-to-engaging-work); [MMS / MSP Manufacturing, 2025](https://www.mmsonline.com/articles/video-transcript-programming-faster-and-winning-jobs-with-ai-cam-software) |
| Machinists aged 55 or older | **31 %** (97k of 309k) | [BLS CPS Table 11b, 2025](https://www.bls.gov/cps/cpsaat11b.htm) |
| Machinist and tool-and-die openings per year | **30,400**, almost all replacing retirees | [BLS Occupational Outlook Handbook](https://www.bls.gov/ooh/production/machinists-and-tool-and-die-makers.htm) |
| Manufacturing jobs that could go unfilled by 2033 | **1.9 million** of 3.8 million needed | [Deloitte & The Manufacturing Institute, 2024](https://themanufacturinginstitute.org/manufacturers-need-as-many-as-3-8-million-new-employees-by-2033/) |
| Processing time as a share of total factory cycle time | often **under 10 %** | a16z, [*A Primer on Factory Economics for Startups*](https://a16z.com/a-primer-on-factory-economics-for-startups/) |

> "Most are operating at a fraction of their potential because of dated software, engineering,
> workflows, and equipment. Advanced technology adoption remains concentrated among the largest firms;
> the long tail has barely been touched."
> — a16z, *The Case for the American Manufacturing Asset Class*

## What it costs a shop

- **Lead time and lost quotes.** A job can't be quoted with confidence, or started, until someone has
  worked out how to make it. One shop in the MMS interview quoted 2–3 weeks where its nearest
  competitor quoted 12 because AI-assisted programming removed weeks of programming time.
- **Cautious programs.** Programs written under time pressure use light cuts and book feeds, and the
  machine pays for that on every part of the order. On the NIST FTC-10 housing our cautious manual-style
  baseline runs 1:49:46 per part; the verified program Instant Machinist picks runs 26:42.
- **Crashes and scrap.** Programs that aren't fully simulated reach the machine with gouges and rapid
  moves into stock. Our verifier caught both in real programs (see
  [instant-machinist/docs/VERIFIER.md](../instant-machinist/docs/VERIFIER.md)).
- **A shrinking pool of programmers.** The people who can do this are retiring faster than they are
  replaced.

## What Instant Machinist changes

| Per new part | Today | Instant Machinist (measured on NIST FTC-10 OP1) |
|---|---|---|
| Drawing review and questions for the customer | part of the 1–4 h | 28.5 s, 8 questions |
| Programming, posting and verification | 1–4 h per new part (≈1 h simple, 4–8 h complex) | **7 min 08 s** for OP1 (top side): 5 strategies, all simulated |
| Machine time per part | cautious program: 1:49:46 | **26:42** (−76 %) |
| Human time | the whole job | ≈ 20 min review and corrections *(assumption: 10 + 10 min)* |

Method and every assumption: [instant-machinist/docs/TIME-SAVED.md](../instant-machinist/docs/TIME-SAVED.md).
Problem slides: [problem-deck.pdf](problem-deck.pdf).
