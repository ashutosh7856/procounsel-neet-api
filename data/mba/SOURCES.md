# MBA / CAT data: sources

All sources were retrieved on **2026-11-11**. Only official IIM / CAT Centre documents are used as data sources.

Hosting note: the official CAT site, https://iimcat.ac.in, is a JavaScript shell hosted by TCS iON. Its PDFs are served from `iimcat.ac.in/per/g06/pub/32842/...` and from the TCS iON CDN `cdn.digialm.com/per/g06/pub/32842/...`. Portal ID 32842 is the CAT portal, and the CAT information bulletins themselves link to these CDN files. Earlier years (CAT 2023 and before) used portal ID 756. The HTML pages of iimcat.ac.in (FAQ, notices) could not be read without a JS browser, so no data was taken from them.

## 1. CAT exam pattern (`cat_exam.json`)

| # | Source | URL | Supports |
|---|---|---|---|
| S1 | CAT 2026 Press Release, IIM Indore, 26 Jul 2026 | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2026/CAT_2026_Press_Release_26-07-2026.pdf | IIM Indore conducts CAT 2026 (Convener Prof. Aditya Billore). Test on 29 Nov 2026 (Sun) in 3 sessions. 120 min. Section I VARC, II DILR, III QA. "exactly 40 minutes ... not allowed to switch from one section to another". Registration 3 Aug to 15 Sep 2026 (original dates). |
| S2 | CAT 2026 Information Bulletin (26-07-26) | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2026/CAT_2026_Information_Bulletin_26-07-26.pdf (mirror: https://iimcat.ac.in/per/g06/pub/32842/EForms/image/CAT2026/CAT_2026_Information_Bulletin_26-07-26.pdf) | Test date 29 Nov 2026. Admit cards 4 to 29 Nov 2026. Results "likely to be declared by the First week of January, 2027". Score valid until 31 Dec 2027. Fee ₹2700 (₹1350 for SC/ST/PwBD). Jurisdiction: Indore. The bulletin gives no section question counts or marking scheme. |
| S3 | CAT 2026 Media Release, 22 Sep 2026 | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2026/CAT_2026_Media_Release_22-09-2026.pdf | Registration deadline stated as 22 Sep 2026, 5 PM, which is later than the 15 Sep date in S1/S2. Fee payment extended to 24 Sep 2026 for those who registered by that deadline. |
| S4 | CAT 2026 Eligibility | https://iimcat.ac.in/per/g06/pub/32842/EForms/image/CAT2026/CAT_2026_Eligibility_26-07-26.pdf | Eligibility and reservation rules (context only). |
| S5 | CAT 2025 Press Release, IIM Kozhikode, 30 Jul 2025 | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2025/CAT_2025_Press_Release.pdf | IIM Kozhikode conducts CAT 2025 (Convener Prof. P N Ram Kumar). 120 min. 3 sections of exactly 40 min each, no switching between sections. |
| S6 | CAT 2025 Media Release, 01 Dec 2025 | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2025/CAT_2025_Media_Release_01_Dec_2025.pdf | Held 30 Nov 2025. 120 min (160 for PwD). 40 min per section. **VARC 24, DILR 22, QA 22, total 68.** |
| S7 | CAT 2024 Media Release, 30 Jul 2024 | https://cdn.digialm.com/per/g06/pub/32842/EForms/CAT24/CAT_2024_Media_Release.pdf | IIM Calcutta conducts CAT 2024 (Convenor Prof. Ramya T. Venkateswaran). 120 min. 3 sections of exactly 40 min, no switching. |
| S8 | CAT 2024 Media Release, 25 Nov 2024 | https://cdn.digialm.com/per/g06/pub/32842/EForms/CAT24/CAT_2024_Media_Release_25_Nov_2024.pdf | Held 24 Nov 2024. 120 min (160 for PwD). **VARC 24, DILR 22, QA 22, total 68.** |
| S9 | CAT 2024 Result Media Release, 19 Dec 2024 | https://iimcat.ac.in/per/g06/pub/32842/ASM/WebPortal/1/PDF/2024_CATMedia_Release_19Th_Dec2024.pdf | CAT 2024 results declared 19 Dec 2024, signed "CAT 2024 Convenor, IIM Calcutta". |
| S10 | CAT 2023 Result Media Release, IIM Lucknow, 21 Dec 2023 | https://cdn.digialm.com/per/g01/pub/756/ASM/WebPortal/12/PDF/Media_Release_CAT_2023_21st_Dec_2023.pdf | **Marking scheme (most recent explicit official statement):** MCQ "Correct Option Marks: 3, Wrong Option Marks: -1", 0 for unattempted. SA (non-MCQ / numeric type-in) "Correct Marks: 3, Wrong Marks: 0", "there was no negative marking". |
| S11 | CAT 2025 Mock Test Links disclaimer | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2025/Mock_Test_Links_V2_2025.pdf | The official mock test has "MCQs/Non-MCQs". Its sequence and number of questions "are only indicative and may vary from year to year". In the actual exam a candidate can move to the next section only after 40 min. |
| S12 | CAT 2024 Mock Test Navigation Guide | https://cdn.digialm.com/per/g06/pub/32842/EForms/CAT24/CAT_2024_Mock_Test_Navigation_Guide_v1.4.pdf | Explains that "Non-MCQ questions" are answered by typing into the on-screen keyboard (the official equivalent of "TITA"). |

Notes on `cat_exam.json`:
- **Question counts.** The 2024 and 2025 counts come from the post-exam official media releases (S8, S6). For **2026 the counts are `null`**: the CAT Centre publishes them only after the test, which is on 29 Nov 2026, after the retrieval date.
- **MCQ vs TITA split per section.** No official document states it for 2024, 2025 or 2026, so it is unknown and not recorded.
- **Marking scheme.** The +3 / -1 / 0 (MCQ) and +3 / 0 / 0 (TITA) values are confirmed explicitly by the official CAT 2023 result release (S10). I found **no retrieved official document for 2024, 2025 or 2026 that restates the marking scheme**: the bulletins, press releases and media releases are all silent on it, and the iimcat.ac.in FAQ HTML could not be read. The values in the 2024–2026 versions are therefore carried forward from the 2023 official statement and are **not separately verified for those years**. Officially the type-in questions are called "Non-MCQ" or "SA (Short Answer)", not "TITA".
- **`sectionOrderLocked: true`.** Official wording (S1, S5, S7): 40 minutes per section and "not allowed to switch from one section to another". The sections are numbered Section I VARC, II DILR, III QA. The mock disclaimer (S11) says the mock's section sequence is indicative only.
- **PwD timing.** PwD candidates get 160 min in total and 53 min 20 s per section (S6, S8). This is not represented in the JSON schema.

## 2. Official CAT past papers

**Finding: NO.** Neither the IIMs nor iimcat.ac.in publish previous-year CAT question papers with answer keys as public downloads.
- **(a) Official IIM-hosted papers.** None found. Searches restricted to iimcat.ac.in and the CAT portal on cdn.digialm.com (portal IDs 32842 and 756) return only advertisements, bulletins, media releases, registration guides, eligibility files and mock-test documents. There are no question-paper PDFs. The closest official item is the **online Mock Test**, which "contains selected questions from previous years' CAT papers" (S11). It is an interactive TCS iON test, not a PDF:
  - Mock link (CAT 2025): https://cdn4.digialm.com//OnlineAssessment/index.html?32842@@M214
  - Mock link (CAT 2025, PwD): https://cdn4.digialm.com//OnlineAssessment/index.html?32842@@M215
  - Terms of use (S11): "No part of this document may be reproduced or copied in any form or by any means ... Such an act shall be subject to appropriate legal action by the CAT Centre 2025". The CAT registration guides and mock guides also carry "© Copyright CAT IIM 2024/2025/2026".
- **(b) Candidate response sheets and provisional answer keys.** These are released each year after the exam through the Objection Management process on iimcat.ac.in, and are reachable **only with the candidate's CAT login ID and password** (S13 below). They are not public downloads. The CAT 2023 release (S10) confirms that an "officially released answer key" existed and was revised after objections.
- **(c) Third-party and coaching copies.** Many coaching and edtech sites host "CAT question paper PDFs" that they reconstructed or collected from response sheets. They are **not official and are not used as sources**.

| # | Source | URL | Supports |
|---|---|---|---|
| S13 | CAT 2024 Media Release, 29 Nov 2024 | https://cdn.digialm.com/per/g06/pub/32842/EForms/CAT24/CAT_2024_Media_Release_29_Nov_2024.pdf | Provisional answer keys were released on 3 Dec 2024. Objections could be raised only "using the CAT application login id and password". |
| S14 | CAT 2025 Admit-card Media Release, 04 Nov 2025 | https://cdn.digialm.com/per/g06/pub/32842/EForms/image/CAT2025/CAT2025_MediaRelease_Admitcard.pdf | The official mock test was available on the CAT website from 12 Nov 2025. |

## 3. CAT 2026 key dates

- Exam: **Sunday, 29 Nov 2026**, three sessions (S1, S2).
- Admit cards: 4 to 29 Nov 2026 (S2).
- Registration: 3 Aug 2026 to **22 Sep 2026** (final, per S3). The original date in S1/S2 was 15 Sep 2026.
- Result: **"likely to be declared by the First week of January, 2027"** (S2, tentative). No exact date has been published.
- Context from previous years (not used for 2026): CAT 2024 results came out on 19 Dec 2024 (S9). CAT 2025 results were reportedly released on 24 Dec 2025, but only third-party sources say so. I did not retrieve an official CAT 2025 results release, so that date is unverified.

## 4. IIM admission policies (Phase D prep)

| IIM | Latest official document found | Batch | Publishes category-wise sectional + overall CAT percentile cutoffs? |
|---|---|---|---|
| Ahmedabad | https://www.iima.ac.in/sites/default/files/2026-09/AdmissionProcedure_PGP_1109_2026.pdf | PGP 2027-29 (CAT 2026) | **Yes.** Table 4 gives non-PwD and PwD cutoffs: General/EWS overall 95 and sectional 85; NC-OBC 90/80; SC 85/75; ST 75/65. PwD: 85/75, 80/70, 75/65, 65/55. Verified from the PDF. |
| Bangalore | https://www.iimb.ac.in/sites/default/files/inline-files/PGP-admissions-process_2027.pdf (process page: https://www.iimb.ac.in/admissions/pgp-admissions/admission-process) | PGP 2027-29 | **Yes**: Annexure I gives the cut-offs used for the 2026-28 batch (CAT 2025), e.g. General VARC 80 / DILR 75 / QA 75 / aggregate 85. Verified in Phase D: the PDF downloads with a browser User-Agent (see §5). |
| Calcutta | https://www.iimcal.ac.in/programs/pgp/admission/admission-policy/admission-procedure-for-domestic-candidates (HTML page; no PDF link found) | MBA 2027-29 (CAT 2026) | **Yes.** Table 1, for example OPEN: VARC ≥80, DILR ≥80, QA ≥75, overall ≥85; also EWS, NC-OBC, SC, ST and PwD rows. The policy says actual cutoffs may be much higher. |
| Lucknow | https://www.iiml.ac.in/sites/default/files/upload/news/2143004504IIML%20Admission%20Policy%20Batch%202026-2028.pdf | MBA / MBA-ABM / MBA-SM 2026-28 (CAT 2025). **The 2027-29 policy was not found.** | **Yes**, in the 2026-28 policy (Table 1). Example: MBA General VARC/DILR/QA 85 each, total 90. |
| Kozhikode | https://iimk.ac.in/uploads/programsmenu/PGP%20Admissions%20Policy%2026-28_20251209102809.pdf | PGP 2026-28 (CAT 2025). **The 2027-29 policy was not found.** | **Yes**, in the 2026-28 policy. Overall and sectional by category, for example GEN 85/75, OBC-NCL/EWS 75/65, SC 65/55, ST/PwD 55/45, plus Class X and XII minimums. |
| Indore | https://iimidr.ac.in/wp-content/uploads/2025/12/Admissions-Procedure-PGP-2026-28-Batch.pdf | PGP 2026-28 (CAT 2025). **The 2027-29 policy was not found.** | **Yes**, in the 2026-28 policy (Table 1). Example: General and EWS QA/DILR/VARC 80 each, overall 90. |

Terms-of-use notes: the CAT Centre documents carry "© Copyright CAT IIM <year>". The mock-test document explicitly forbids reproduction (S11). I found no explicit licence for reuse of the IIM admission-policy PDFs, so link to them rather than rehost them.

## 5. Phase D: IIM programmes and minimum CAT thresholds (`programs/*.json`)

Retrieved **2026-11-11** from each IIM's own admission policy, fee page, or final placement report, or from NIRF data. The NIRF data is the institute's submitted-data PDF, either on nirfindia.org or hosted by the IIM itself. No coaching or aggregator site is used as a source; several aggregator figures were checked and found wrong. Every figure in the files carries `source {kind:"official", title, url, year, retrievedAt}`, and each source has a short verbatim `quote` (stored for audit, not returned by the API). Unknown values are `null`.

**What the cutoffs are.** They are the **minimum eligibility thresholds** an IIM publishes for its first, CAT-based shortlisting stage, called "minimum percentile requirements", "Stage 1 eligibility", "JAP/CAP registration minimums" and so on. They are **not closing percentiles or final cut-offs.** The IIMs say outright that the percentiles actually needed for an interview call are higher, for example IIMB: "The scores of those called for interviews were higher". Final selection also uses academics, work experience, diversity points and WAT/PI under each IIM's own policy.

**Batches.** Only IIM Ahmedabad and IIM Calcutta had published their **2027-29 (CAT 2026)** policy by the retrieval date. Every other institute uses its official **2026-28 (CAT 2025)** policy, and its `policyBatch` says so. IIM Bangalore's 2027-29 procedure prints the cut-offs it applied to 2026-28, so those are recorded as 2026-28.

**How the files encode it.**
- A policy that gives a single PwD/DAP row is expanded to all five categories with `pwd: true`.
- A single "sectional" minimum is written to each of VARC, DILR and QA.
- Jammu, Sirmaur and Sambalpur publish gender-specific minimums, so those records carry `gender`.
- Non-CAT requirements go in `notes` and are **not checked** by the API: Class X/XII/graduation minimums, a positive raw score in every section, and work experience for IIML MBA-SM.

### 5.1 Cutoff coverage (21 institutes)
| Institute | Policy batch | Cutoff source (official) | Gender-specific? | Notes |
|---|---|---|---|---|
| IIM Ahmedabad | 2027-29 | https://www.iima.ac.in/sites/default/files/2026-09/AdmissionProcedure_PGP_1109_2026.pdf | no | overall + sectional; 10 records |
| IIM Amritsar | 2026-28 | https://iimamritsar.ac.in/academics/mba/admission | no | overall + sectional; 10 records |
| IIM Bangalore | 2026-28 | https://www.iimb.ac.in/sites/default/files/inline-files/PGP-admissions-process_2027.pdf | no | overall + sectional; 10 records |
| IIM Bodh Gaya | 2026-28 | https://iimbg.ac.in/wp-content/uploads/2026/04/EOI-Percentile-Cut-offs-for-CAP-2026_IIM-Bodh-Gaya.pdf | no | overall + sectional; 10 records |
| IIM Calcutta | 2027-29 | https://www.iimcal.ac.in/programs/pgp/admission/admission-policy/admission-procedure-for-domestic-candidates | no | overall + sectional; 10 records |
| IIM Indore | 2026-28 | https://iimidr.ac.in/wp-content/uploads/2025/12/Admissions-Procedure-PGP-2026-28-Batch.pdf | no | overall + sectional; 10 records |
| IIM Jammu | 2026-28 | https://www.iimj.ac.in/programs/post-graduate-program-pgp/admission-policy.php | yes | overall + sectional; 30 records |
| IIM Kashipur | 2026-28 | https://www.iimkashipur.ac.in/admin/pdf/176694001586.pdf | no | overall + sectional; 10 records |
| IIM Kozhikode | 2026-28 | https://iimk.ac.in/uploads/programsmenu/PGP%20Admissions%20Policy%2026-28_20251209102809.pdf | no | overall + sectional; 10 records |
| IIM Lucknow | 2026-28 | https://www.iiml.ac.in/sites/default/files/upload/news/2143004504IIML%20Admission%20Policy%20Batch%202026-2028.pdf | no | overall + sectional; 30 records |
| IIM Mumbai | 2026-28 | https://iimmumbai.ac.in/admissions/assets/admission-policy-2026-MBA.pdf | no | overall + sectional; 10 records |
| IIM Nagpur | 2026-28 | https://www.iimnagpur.ac.in/admissions/mba/admissions-policy/ | no | overall + sectional; 10 records |
| IIM Raipur | 2026-28 | https://iimraipur.ac.in/wp-content/uploads/2025/12/JAP-2026-MBA-Admission-Policy-Common-v25.12.2025.pdf | no | overall + sectional; 10 records |
| IIM Ranchi | 2026-28 | https://iimranchi.ac.in/media/2026/04/Admission-Criteria-2026.pdf | no | overall + sectional; 10 records |
| IIM Rohtak | 2026-28 | https://www.iimrohtak.ac.in/panel/assets/images/prospectus/17038426332257.pdf | no | overall only; 10 records |
| IIM Sambalpur | 2026-28 | https://iimsambalpur.ac.in/wp-content/uploads/2026/01/MBA-2026-28-Admission-Policy-1.pdf | yes | overall only; 10 records |
| IIM Shillong | 2026-28 | https://www.iimshillong.ac.in/wp-content/uploads/2026/01/PGP-2026-28-Admission-Process.pdf | no | sectional only; 9 records |
| IIM Sirmaur | 2026-28 | https://admissions.iimsirmaur.ac.in/mba-admissions-policy-2026 | yes | overall + sectional; 20 records |
| IIM Tiruchirappalli | 2026-28 | https://www.iimtrichy.ac.in/en/pgpm-admin-criteria | no | overall + sectional; 10 records |
| IIM Udaipur | 2026-28 | https://mba.iimu.ac.in/admissions/ | no | overall + sectional; 10 records |
| IIM Visakhapatnam | 2026-28 | https://www.iimv.ac.in/programs/pgp/admissions/pgp-adms-adm-prcs-crtra | no | overall + sectional; 10 records |

Cutoff caveats:
- **IIM Shillong** has sectional minimums only (no overall) and **no NC-OBC row**, so NC-OBC shows as unknown.
- **IIM Rohtak and IIM Sambalpur** have overall minimums only.
- **IIM Sambalpur's General minimum** is 90, or 85 for women and for men with at least 1 year of relevant work experience. Only the Female row (85) is stored. General (Male) shows as unknown because work experience cannot be checked.
- **IIM Lucknow** has separate tables for MBA, MBA-ABM and MBA-SM, which are stored per programme.
- **IIM Kashipur** has two tables. Its own MBA policy page still shows an older CAT-2024 table (General 95) with a note that 2026-28 cutoffs "will be updated soon in accordance with JAP 2026". The newer JAP 2026 table, hosted on iimkashipur.ac.in, is used.
- **IIM Raipur's** own page defers to the common JAP 2026 policy, hosted on iimraipur.ac.in as coordinator. Those registration minimums are used.
- **IIM Ranchi and IIM Tiruchirappalli** publish their own higher PI-shortlisting minimums, and those are used.
- **IIM Bodh Gaya:** the final CAP 2026 EOI cut-offs for gender-neutral seats are used. The lower supernumerary-girls cut-offs are in `notes`.
- **IIM Jammu** states that its cut-offs "can be higher/lower ... after the declaration of CAT 2025 result". Its Transgender rows equal its Female rows.
- **IIM Sirmaur** publishes Male and Female rows only, so Transgender shows as unknown.
- **The consolidated CAP 2026 cut-off PDF** on cap2026.iimj.ac.in could not be fetched because of a TLS certificate error. The identical tables on each institute's own site were used instead.

### 5.2 Programme facts
| Institute | Programme | Fee total | Intake | Median salary (year) | Salary source |
|---|---|---|---|---|---|
| IIM Ahmedabad | MBA-PGP | ₹2,750,000 | 455 | ₹3,700,000 (2026) | https://www01.iima.ac.in/iprs/gallery/2026/PGP_Audit_Report_Finals_2026.pdf |
| IIM Amritsar | MBA | ₹1,950,000 | 302 | ₹1,229,000 (2025) | https://iimamritsar.ac.in/img/IIM-Amritsar20260216.pdf |
| IIM Bangalore | PGP | ₹2,600,000 | 598 | ₹3,475,000 (2026) | https://www.iimb.ac.in/sites/default/files/inline-files/Placement-Report-2026.pdf |
| IIM Bodh Gaya | MBA | ₹1,796,000 | 300 | ₹1,212,000 (2025) | https://iimbg.ac.in/wp-content/uploads/2026/04/Finals_Audited-Report-PGP-2023-25.pdf |
| IIM Calcutta | MBA | ₹2,700,000 | 545 | ₹3,500,000 (2026) | https://www.iimcal.ac.in/sites/default/files/2026-08/f-61.pdf |
| IIM Indore | PGP | ₹2,400,000 | 633 | ₹2,500,000 (2026) | https://iimidr.ac.in/wp-content/uploads/2026/08/Final-Placement-Report-2026.pdf |
| IIM Jammu | MBA | ₹2,280,756 | 300 | ₹1,580,000 (2025) | https://www.iimj.ac.in/sites/default/files/2025-02/NIRF%202026_Final%20Submitted%20Data.pdf |
| IIM Kashipur | MBA | ₹2,080,000 | — | ₹1,446,950 (2025) | https://www.iimkashipur.ac.in/uploads/report/176597088439.pdf |
| IIM Kozhikode | PGP | ₹2,350,000 | 591 | ₹2,750,000 (2025) | https://iimk.ac.in/uploads/userfiles/Final-Placements-Report-2025.pdf |
| IIM Lucknow | MBA | ₹2,050,000 | 621 | ₹3,290,000 (2026) | https://www.iiml.ac.in/sites/default/files/2026-07/Final%20Placement%20Report%202024-26.pdf |
| IIM Lucknow | MBA-ABM | ₹2,050,000 | — | — (2026) | — |
| IIM Lucknow | MBA-SM | — | — | — | — |
| IIM Mumbai | MBA | ₹2,100,000 | 534 | ₹3,400,000 (2025) | https://iimmumbai.ac.in/storage/uploads/pages/pages_docs/nirf_2026.pdf |
| IIM Nagpur | MBA | ₹2,100,000 | 340 | ₹1,631,600 (2026) | https://www.iimnagpur.ac.in/wp-content/uploads/2026/10/Final-Placement-Report_.pdf |
| IIM Raipur | MBA | ₹2,008,000 | 331 | ₹1,840,000 (2025) | https://alumni.iimraipur.edu.in/IIMRaipurAnualReport/FP_Report_2023-25.pdf |
| IIM Ranchi | MBA | ₹1,920,000 | 380 | ₹1,800,000 (2026) | https://iimranchi.ac.in/media/2024/01/Audited-Final-Placement-Report-2025-26-compressed.pdf |
| IIM Rohtak | PGP | ₹1,790,000 | 264 | ₹1,800,000 (2026) | https://www.iimrohtak.ac.in/panel/assets/images/placement/Final%20Placement%20Report%202024-26.pdf |
| IIM Sambalpur | MBA | ₹1,955,000 | 320 | ₹1,502,692 (2025) | https://iimsambalpur.ac.in/uploads/documents/20261022145500_b916f33394b8821e.pdf |
| IIM Shillong | PGP | — | 382 | ₹2,600,000 (2026) | https://www.iimshillong.ac.in/wp-content/uploads/2026/05/IIM-Shillong-Placement-Report-2024-26-Batch.pdf |
| IIM Sirmaur | MBA | ₹2,100,000 | 285 | ₹1,420,000 (2025) | https://iimsirmaur.ac.in/sites/default/files/2026-04/INDIAN%20INSTITUTE%20OF%20MANAGEMENT%20SIRMAUR20260402-.pdf |
| IIM Tiruchirappalli | PGPM | ₹1,950,000 | 410 | ₹1,810,000 (2024) | https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Management/IR-M-S-8948.pdf |
| IIM Udaipur | MBA | — | 375 | ₹1,801,861 (2026) | https://placements.iimu.ac.in/wp-content/uploads/2026/10/IIM-Udaipur-MBA-Final-Placement-Audit-Report-2024-26_3rd-draft.pdf |
| IIM Visakhapatnam | PGP | ₹2,358,590 | — | ₹1,400,000 (2026) | https://www.iimv.ac.in/placement/placement-reports |

Programme-fact caveats:
- **Fees.** `feeTotal` is the whole-programme fee as officially stated. `feeNote` says what it covers and which batch, and the exceptions are noted there:
  - IIMA's latest stated fee is for 2025-27, and IIMB's and IIMC's are for 2024-26.
  - IIM Mumbai's ₹21,00,000 includes a ₹50,000 refundable deposit.
  - IIM Visakhapatnam's figure is 2 × its official year total.
  - Several fee PDFs are scanned and were read from rendered pages: Amritsar, Sambalpur, Ranchi and Raipur. Their quotes say so.
- **Fee `null`:**
  - **IIM Udaipur** publishes only term-wise totals, not a programme total.
  - **IIM Shillong** has published no 2026-28 fee; its finances page has only 2024-26 term payments that include deposits and mess advances.
  - **IIM Lucknow MBA-SM** has no figures.
- **Intake.** Most intake figures are NIRF "sanctioned (approved) intake" for **all 2-year PG programmes combined**, not the flagship alone. `intakeNote` says so. These programme-specific intakes come from the institutes' own documents:
  - Rohtak 264
  - Nagpur 340
  - Udaipur 375
  - Bodh Gaya 300
  - Sambalpur 320
  - Jammu "around 300"
- **Intake `null`:**
  - **IIM Kashipur and IIM Visakhapatnam:** only NIRF all-programme figures exist.
  - **IIML MBA-ABM and MBA-SM:** IIML publishes no programme-wise seats.
- **Median salary.** Each figure is from the latest official final placement report, or from NIRF where that is the latest official figure. `medianSalaryYear` is the graduating year, and `salaryNote` gives the scope, e.g. IIMA's "Maximum Earning Potential" median, or combined programmes at IIMB, IIML, IIMK and IIMI. Two substitutions:
  - **IIM Tiruchirappalli** uses NIRF 2025 (graduates of 2023-24). Its 2024-26 figure on iimtrichy.ac.in is from an interim, **unaudited** update.
  - **IIM Jammu** uses its own NIRF 2026 data (2024-25). Its 2024-26 placement report is hosted on Google Drive (₹15.00 LPA, noted).
- **NIRF 2026** institution PDFs were not yet on nirfindia.org (404). Where an IIM hosts its own NIRF 2026 submission, that copy is used: Amritsar, Sirmaur, Mumbai and Jammu.

**Not covered:**
- **Programmes:** the IIMs' other programmes (e.g. IIMK PGP-Finance and PGP-LSM, IIMI IPM, IIM Mumbai MBA-OSCM and MBA-SM, IIM Ranchi MBA-HRM and MBA-BA) and executive programmes.
- **Cutoffs:** the actual interview-call or closing percentiles. These are not officially published in a comparable form.

## 6. MBA entrance exams (`exams/*.json`) and the Maharashtra MBA CAP cut-offs

All sources were retrieved on **2026-11-11**. Only official sources from the conducting bodies are used. Each exam file has its own `sources[]` array, with a `supports` note for every figure. Unknown values are `null`.

### 6.1 Maharashtra MBA/MMS CAP Round I cut-offs (`exams/mah-mba-cap-cutoffs.json`)
- **Year and round.** A.Y. **2026-27**, the latest completed cycle: the last admission date was 14 Sep 2026. The data is from **CAP Round I**, Maharashtra & Minority seats.
- **Source.** The official PDF "Cut Off Merit for Maharashtra & Minority Seats CAP Round-I ... MBA/MMS for the Academic Year 2026-27" (432 pages) from the State CET Cell.
  - It is listed on the MBA/MMS CAP 2026-27 portal https://mba2026.mahacet.org.in/mba_26/home, under Seat Matrix & Cut Off, 2026, CAP1, MH. The portal is linked from https://cetcell.mahacet.org/cap-_2026-27/.
  - The file is served by the portal backend: `https://mbaproject26api.4pindia.com/platform_api_26/common/getFile?filename=PG_MBA_CAP1_Cutoff_All_Institutes_2025_26.pdf&flag=11&round=cap1&course_name=mba`.
  - That URL needs the browser `Origin`/`Referer` headers of `https://mba2026.mahacet.org.in`. The server filename says 2025_26, but the PDF title says 2026-27.
- **Parsed output.**
  - **4,400 rows**: 397 institutes, 429 course choice codes, 0 mismatched blocks.
  - Each row has the institute code, name and city, the course code, the seat type (HU, OHU, State Level or Minority), the official category code (e.g. GOPENS, LOBCH, TFWS, EWS, MI), the closing merit number, and the **closing merit score**.
  - The PDF legend says "Figures in bracket Indicates Merit Score". MBA CAP merit is on the percentile basis in CET, CAT or CMAT (2025-26 Information Brochure, rule on merit), so the merit score is stored as `closingPercentile`.
- **City.** It is taken only from the text after the last comma in the official institute name. 56 institutes have no city in their name, so their city is null.
- **Not parsed.** CAP Rounds II–IV and the All-India-seat PDFs were not parsed. Their URLs are in `otherOfficialFiles`. Rounds II–IV use several stages and sparse columns, so they need positional parsing.
- **Previous year.** For the 2025-26 cut-off PDFs (CAP I–III, MH and AI), see https://mba2025.mahacet.org.in/cetmba25/mba25/index.php?show=home.
- **Not used.** The CET Cell "Cutoff Explorer" page (https://cetcell.mahacet.org/cutoff-explorer/) is password-protected.

### 6.2 MAH-MBA/MMS-CET (`exams/mah-mba-cet.json`)
| Source | URL | Supports |
|---|---|---|
| Information Brochure MAH-MBA/MMS-CET 2026 | https://cetcell.mahacet.org/wp-content/uploads/2023/12/MAH-MBA-MMS-CET-2026-Information-Brochure.pdf | Eligibility; fee ₹1500 (Open/OMS) or ₹1300 (MH reserved/PwD) per attempt, ₹3000 or ₹2600 for both attempts; 75/25/50/50 questions, 200 marks, 150 min, no negative marking; best of two attempts |
| Syllabus & Marking Scheme 2026 (scanned) | https://cetcell.mahacet.org/wp-content/uploads/2023/12/Syllabus-Technical-2026.pdf | Syllabus areas and marking scheme |
| Registration extension notice (11/02/2026) | https://cetcell.mahacet.org/wp-content/uploads/2023/12/CET-Registration-Extension-Notice-MBA-MHT-CET-CET-2026.pdf | Registration and exam dates |
| Final CET dates (16/03/2026) and 2nd-attempt notice (26/04/2026) | https://cetcell.mahacet.org/wp-content/uploads/2023/12/Technical-Education-CET-final-dates_2026.pdf, https://cetcell.mahacet.org/wp-content/uploads/2026/04/PUBLIC-NOTICE-for-MBA_MHT_Second-Attmp.-Exam-Date-1.pdf | 06–08 Apr 2026 and 09 May 2026 |
| Notices list | https://cetcell.mahacet.org/cms-notices/ | Results: 30/05/2026 (1st attempt), 12/06/2026 (2nd attempt) |
| MBA/MMS CAP Admission Notice No. 1 (02/07/2026) | https://cetcell.mahacet.org/wp-content/uploads/2026/07/MBA-MMS-CAP-AY-26-27-Schedule-Notice-No.1-Upto-Merit-List.pdf | CAP eligibility and accepted exams (CET/CAT/CMAT/XAT/ATMA/MAT/GMAT); CAP fee; registration 02–12 Jul 2026 |
| UG & PG Information Brochure 2025-26 (CAP rules) | https://mba2025.mahacet.org.in/cetmba25/mba25/staticFiles/mba/Information_Brochure_UG&PG_2025_26.pdf | Percentile-based merit; CAP Rounds I–IV; HU/OHU logic |

Gap: **MAH-MBA/MMS-CET 2027 had not been notified** by 2026-11-11, so the file describes the 2026 cycle.

### 6.3 CAT (`exams/cat.json`)
This file is built from the sources in §1 (S1–S6, S10) and adds the eligibility PDF (S4), the fee (₹2700, or ₹1350 for SC/ST/PwBD), the registration dates (3 Aug to 22 Sep 2026, extended), the admit cards, the exam date (29 Nov 2026), the result date (first week of Jan 2027, tentative) and the score validity (31 Dec 2027). `cat_exam.json` itself was not modified.

### 6.4 Other exams
Each file lists its full sources in `sources[]`. The main official URLs and the gaps are below.

**XAT 2027** (`exams/xat.json`)
- **Main sources:**
  - https://xatonline.in/assets/pdf/xat-bulletin-2027.pdf
  - https://xatonline.in/assets/pdf/xat-2027-overview.pdf (image-only; read from rendered pages)
  - https://xatonline.in/faq
  - https://xatonline.in/assets/pdf/xlri-admission-prospectus-2027.pdf
- **Previous-cycle values:** the mode (computer-based) and the 180-min total come from the labelled XAT 2026 instructions.
- **Null:** per-section minutes, because Part 1 is a single shared 170-min block, and score validity, which is not stated.
- **Ignored:** a "January 5, 2027" notice on the homepage, because it is commented out in the page source.

**SNAP 2026** (`exams/snap.json`)
- **Main sources:**
  - https://www.snaptest.org/documents/SNAP-2026-Bulletin.pdf
  - https://www.snaptest.org/snap-important-dates
  - https://www.snaptest.org/snap-exam-syllabus
  - https://www.snaptest.org/eligibility
- **Null:** per-section minutes.

**NMAT 2026** (`exams/nmat.json`)
- **Main sources:**
  - https://www.mba.com/exams/nmat
  - the NMAT terms PDF on mba.com
  - gmac.com NMAT articles
- **Blocked:** most mba.com subpages are behind Incapsula bot protection.
- **Conflict 1 (Language Skills timing):** used 28 min, from the official terms; it adds up to 120. A GMAC article says 38 min.
- **Conflict 2 (closing dates):** used the mba.com India dates, 20 Aug to 31 Oct 2026, and the test window of 2 Nov to 20 Dec 2026. An August GMAC article gives earlier closing dates.
- **Null:** the retake window dates.

**GMAT Focus Edition** (`exams/gmat.json`)
- **Main sources:** gmac.com exam-scores and policies (Oct 2024 PDF), and mba.com.
- **Attempts:** the earlier 8-attempt lifetime limit is not included, because GMAC says it has been removed.
- **Fees:** USD 275 at an India test centre. The online fee, USD 300, is a general figure and not India-specific.
- **Null:** the INR fee.
- **Accepting institutes:** only ISB is named, because the mba.com list of Indian schools was blocked.

**CMAT 2026** (`exams/cmat.json`)
- **Main sources:**
  - https://cmat.nta.nic.in/
  - the NTA CMAT 2026 Information Bulletin, hosted on cdnbbsr.s3waas.gov.in (NTA's government web host)
  - NTA public notices on nta.ac.in
- **CMAT 2027 not yet notified:** the NTA About page only mentions CMAT-2027 for the 2027-28 session.
- **Null:** score validity and the official institute list; NTA says only "accepted by all AICTE-approved institutions".

**MAT December 2026** (`exams/mat.json`)
- **Main sources:**
  - https://mat.aima.in/
  - https://aima.in/mat/faq/
  - https://aima.in/mat/participating-b-schools/
- **Null:** IBT mode (not currently listed), marks per correct answer, and per-section minutes.

## 6. Non-IIM CAT percentile cutoffs (`cat-cutoffs/*.json`, `cat-cutoffs/index.json`)

Retrieved **2026-11-11**. This section covers B-schools other than the IIMs that accept CAT. A figure is recorded only when the institute **itself** publishes it, in an admission or eligibility page, an official notice or brochure, or its AICTE mandatory disclosure. For JBIMS the source is the State CET Cell's own CAP list. Coaching and aggregator "expected cutoffs" were used, at most, to find an official URL and were never used as a source. Unknown values are `null`. Each cutoff row has `stage`:
- `minimum_to_apply` is the eligibility floor for applying.
- `shortlisting` is the minimum for a GD/WAT/PI call.
- `final` is a closing or admitted cut-off that the institute disclosed for a past batch.

Each row also carries a short verbatim `quote`.

### 6.1 Institutes with an official CAT figure (12 files)
| Institute | Programme | Batch | Stage | General overall (sectional) | Source |
|---|---|---|---|---|---|
| DoMS IISc Bangalore | M.Mgt | 2026-28 | shortlisting | 98.85 | https://www.iisc.ac.in/wp-content/uploads/2026/04/MMgt_cutoff_2026.pdf |
| VGSoM IIT Kharagpur | MBA | 2026-28 | shortlisting | 90 | https://som.iitkgp.ac.in/MBA/selectionprocess.php |
| Goa Institute of Management | PGDM (core) | 2025-27 | final | 90 | https://gim.ac.in/sites/default/files/inline-files/Mandatory%20Disclosure-2025-26.pdf |
| SPJIMR | PGDM | 2027-29 | minimum_to_apply | 85 (75 each section; same for all categories) | https://www.spjimr.org/wp-content/uploads/2026/09/eligibility-domestic-pgdm-27-29.pdf |
| IIT Jodhpur SME | MBA | 2026-28 | shortlisting | 80 (55 sectional), with category rows | https://www.iitj.ac.in/PageImages/Gallery/03-2026/Cutoffs-for-shortlisting-candidates-for-the-Personal-Interview-2026-639088599885932754.pdf |
| DoMS IIT Kanpur | MBA | 2026-28 | minimum_to_apply | 80 | https://iitk.ac.in/doms/data/docs/programs/mba/Information-Brochure-MBA-2026.pdf |
| FORE School of Management | PGDM (also IB/FM 70, BDA 60) | 2025-27 | final | 80 | https://www.fsm.ac.in/pdf/mandatory.pdf |
| WeSchool (Welingkar) Mumbai | PGDM (other programmes 75/70; Bengaluru 75/70) | 2026-28 | shortlisting | 80 | https://www.welingkar.org/programmes/full-time-programme-in-mumbai/pgdm |
| IMT Nagpur | PGDM | 2027-29 | minimum_to_apply | 70 | https://www.imtnagpur.ac.in/admissions/ |
| IFMR GSB, Krea University | MBA | 2027-29 | minimum_to_apply | 70 | https://krea.edu.in/ifmr-gsb/admissions/mba/eligibility/ |
| BIMTECH | PGDM | **2021-23** | final | 72.5, **stale and not indexed** | mandatory disclosure on bimtech.ac.in (see file) |
| JBIMS | MMS | 2025-27 | final (CAP AI round I) | 99.99 closing score, **not indexed** | State CET Cell CAP cut-off lists (see file) |

Caveats:
- **IIT Jodhpur.** The page is https://iitj.ac.in/schools/en/cat-cut-offs. iitj.ac.in fails TLS verification, so the official PDF was read from its Internet Archive capture. That page also links the cut-off PDFs for 2024-26 and 2025-27.
- **JBIMS.** The CET Cell All-India merit list mixes CAT, CMAT, MAH-CET and other exams, and does not say which exam a closing score comes from. It is therefore **not a CAT percentile** and is excluded from the index.
- **BIMTECH.** The only disclosure linked on the site is for AY 2021-22. Its 2027-29 page says the cut-off is "not pre-defined".
- **"final" rows** for GIM and FORE are last year's admission cut-offs from the mandatory disclosure. They are not a rule for the next batch.
- **Sectional values.** A single "sectional" value is written to each of VARC, DILR and QA.

### 6.2 Checked, no official CAT cutoff (`index.json` → `checkedNoOfficialCutoff`)
- **No CAT cutoff published:**
  - FMS Delhi
  - MDI Gurgaon
  - SJMSOM IIT Bombay and DoMS IIT Madras. Both publish only composite-score shortlisting.
  - DoMS IIT Roorkee
  - IIT (ISM) Dhanbad
  - IIT Mandi
  - IMT Ghaziabad
  - K J Somaiya
  - TAPMI
  - LBSIM
  - IRMA
  - Jaipuria
  - UBS Chandigarh
- **States it has no fixed cutoff:**
  - **IMI Delhi:** "no fixed cut-off".
  - **Great Lakes:** gives only "desired ranges" (Chennai 85-98, Gurgaon 80-96) and says these are not hard cutoffs.
- **IMT Hyderabad:** the 90 figure appears only in a marketing blog FAQ on the institute's blog subdomain. That is not an admission policy or notice, so it is not recorded.
- **Could not be verified** because the hosts fail TLS checks and no archive copy exists:
  - **IIFT.** It now admits through CAT. The cutoffs would be in the application-portal PDF on applyadmission.net.
  - **DMS IIT Delhi.** The 2026 shortlisting-criteria PDF. Only its Admission Index weightages were readable.
- **XIM Bhubaneswar:** says it posts its cutoffs in February. The notice was not reachable. Re-check after February 2027.
- **XLRI:** does not accept CAT.

### 6.3 `index.json`
- **Bands.** For X = 99, 95, 90, 85, 80, 70 and 60, `bands[X].meets` lists the institutes whose **published General-category overall** threshold is ≤ X. For SPJIMR, its all-category figure is used.
- **Coverage.** It includes the 21 IIMs, using the flagship-programme General row from `programs/*.json`:
  - For Jammu and Sirmaur, the Male row is used, and the Female minimum is noted.
  - For Sambalpur, the General minimum of 90 is used, with the 85 exception noted.
  - IIM Shillong has no overall minimum, so it is not in any band.
- **Sectional minimums** are shown per institute in `generalSectional` and are **not** checked in the bands.
- **Not guarantees.** These are published minimums and shortlisting cut-offs, not closing percentiles. Actual calls usually need higher scores, and academics, work experience and WAT/PI also count.
- **Counts:** 99 → 30, 95 → 26, 90 → 22, 85 → 12, 80 → 6, 70 → 2, 60 → 0.

## 7. Non-IIM B-schools (`colleges/*.json`) and NIRF Management ranking (`nirf-management.json`)

Retrieved **2026-11-11**. Sources are the institute's own website, brochures, fee pages and final placement reports, or NIRF data the institute submitted (some institutes host their own copy). For Maharashtra CAP institutes, State CET Cell CAP documents are also used. No coaching or aggregator site is used. Unknown values are `null`. Every non-null figure maps to a URL in `programs[].sources` or in `sources[].supports`. Median and average salaries are stored separately; where only one is published, the other is `null`.

### NIRF Management ranking (`nirf-management.json`)
- **Year captured:** **India Rankings 2025: Management**, released 4 Sep 2025. Source: https://www.nirfindia.org/Rankings/2025/ManagementRanking.html, copy fetched on 2026-11-11.
- **2026 ranking:** https://www.nirfindia.org/Rankings/2026/ManagementRanking.html returned **404** on 2026-11-11, so the 2026 ranking is not yet published.
- **What the file holds:** ranks 1-100. Each row has the NIRF ID, name, city and state exactly as printed, the score, the five parameter scores (TLR, RPC, GO, OI, PERCEPTION) and the link to the institute's NIRF data PDF.
  - **Ties:** two institutes share rank 46 and two share rank 57, so there are no ranks 47 or 58.
  - **101-125 band:** NIRF publishes it without individual ranks. It is not included.
- **Top-10 check:** the top 10 matches the PIB release of 04 Sep 2025, https://www.pib.gov.in/PressReleasePage.aspx?PRID=2163711.
- **Access note:** nirfindia.org later started returning HTTP 403 to automated fetches. The institute NIRF PDFs were not re-fetched from it; they were taken from copies the institutes host themselves.
- **Not in the top 100:** FMS Delhi, JBIMS, SCMHRD, TISS, BIMM and PUMBA (`managementRank: null`).
- **IIT entries:** for IIT Bombay (SJMSOM) and IIT Delhi (DMS) the ranked entity is the IIT. For NMIMS it is the whole university, not SBM alone.

### Per-institute sources
| Institute | Field(s) | Source title | URL |
|---|---|---|---|
| XLRI | fee (approx. 15.3 L/yr), exams, selection, key dates | XLRI Admission Prospectus 2027 | https://cloud-server.xlri.ac.in/file/6ae1febe65cd3e58180bb565 |
| FMS Delhi | fee (approx. ₹65,075/semester), intake, selection weights | FMS Information Bulletin MBA FT 2027-29 | https://www.fms.edu/static/programmes/MBA_2027.pdf |
| FMS Delhi | median/average 2024-26 | FMS Final Placement Report 2024-26 | https://www.fms.edu/static/corporate-relations/placementReports/Final_Placement_Report_2024-2026.pdf |
| FMS Delhi | key dates | FMS online admissions 2027 portal | https://fmsadmissions.co.in/ |
| MDI Gurgaon | fee, selection weights, key dates | MDI PGDM admissions page 2027-29 | https://mdi.ac.in/admissions/post-graduate-diploma-in-management-pgdm |
| MDI Gurgaon | median/average (PGDM, PGDM-HRM) 2024-26 | MDI Final Placement Report 2024-26 | https://mdi.ac.in/resources/admin_uploads/announcement/17810688232026-Placement_compressed.pdf |
| MDI Gurgaon | intake (all PG programmes combined) | MDI NIRF 2026 data | https://mdi.ac.in/resources/admin_uploads/about/nirf-2026.pdf |
| IIFT Delhi | fee (2026-28), seats, selection, dates | IIFT MBA(IB) 2027-29 brochure | https://www.iift.ac.in/uploads/manage-files/2026/10/brochure-mba-2027.pdf |
| IIFT Delhi | average 2023-25 | IIFT Final Placement Highlights 2025 | https://www.iift.ac.in/uploads/manage-files/2025/12/finalplacementhighlight2025.pdf |
| IMT Ghaziabad | fee 2027-29 | IMT PGDM fee structure | https://web.imt.edu/downloadfiles/admissions/2026/fees/fees-pgdm-imtg.pdf |
| IMT Ghaziabad | exams, selection, key dates | IMT admissions page | https://www.imt.edu/admissions/pgdm/ |
| IMT Ghaziabad | median/average 2024-26 | IMT placements page (image) | https://www.imt.edu/placements/ |
| IMT Ghaziabad | intake (all PG programmes combined) | IMT NIRF 2026 data | http://web.imt.edu/DownloadFiles/NIRF2026.pdf |
| SPJIMR | intake, cutoffs (CAT/GMAT 85 overall, 75 sectional), selection, deadline | PGDM 2027-29 eligibility | https://www.spjimr.org/wp-content/uploads/2026/09/eligibility-domestic-pgdm-27-29.pdf |
| SPJIMR | fee 2027-29 | PGDM fees & scholarships | https://www.spjimr.org/course/post-graduate-diploma-in-management-pgdm/fees-scholarships/ |
| SPJIMR | median/average, Class of 2026 (PGDM and PGDM-BM combined) | Placement press release | https://www.spjimr.org/newsroom/press-release/spjimr-announces-100-final-placements-for-the-pgdm-and-pgdm-bm-class-of-2026/ |
| SPJIMR | key dates | 2027-29 applications press release | https://www.spjimr.org/newsroom/press-release/spjimr-opens-applications-for-pgdm-and-pgdm-bm-programmes-for-2027-29/ |
| JBIMS | first-year fee by category, CAP process | MMS admission instructions A.Y. 2026-27 | https://jbims.edu/uploads/announcement/Reporting_Payment_Details_for_A_Y_2026-271.pdf |
| JBIMS | median/mean 2024-26 | Final Placement Report 2024-26 | https://jbims.edu/uploads/placementreport/Final_Placement_Report_2024-265.pdf |
| JBIMS | intake (NIRF, combined) | JBIMS-hosted NIRF 2026 data | https://jbims.edu/uploads/notice/Jamnalal_Bajaj_Institute_of_Management_Studies20260402-.pdf |
| JBIMS | CAP Round I cutoff (State CET Cell) | CAP-I cut-off merit, MBA/MMS A.Y. 2026-27 | https://mbaproject26api.4pindia.com/platform_api_26/common/getFile?filename=PG_MBA_CAP1_Cutoff_All_Institutes_2025_26.pdf&flag=11&round=cap1&course_name=mba |
| NMIMS SBM | fee (₹13.5 L/yr, 2026-28), selection, dates | NMAT 2026 admission handout | https://nmat.nmims.edu/docs/Handout-Admission-NMAT-2026-Final.pdf |
| NMIMS SBM | intake | NMAT 2025 admission handout | https://nmat.nmims.edu/docs/NMAT-New-Handout-2025.pdf |
| NMIMS SBM | average (MBA Core 2024-26) | SBM Final Placement Report 2025-26 | https://sbm.nmims.edu/docs/2026/Finals-SBM-NMIMS-Mumbai-2025-26.pdf |
| KJSIM | fee 2026-28, intake, weightage | KJSIM MBA admission page | https://kjsim.somaiya.edu/en/admission/mba/ |
| KJSIM | median 2024-26 | Current placement highlights | https://kjsim.somaiya.edu/en/current-placement-highlights/ |
| Welingkar | fee (₹7 L/yr), intake, median/average 2023-25 | PGDM 2026-28 brochure | https://www.welingkar.org/downloads/PGDM_Brochure_Final_2026_2028_Dec_2025.pdf |
| Welingkar | weightage, cutoffs | PGDM Mumbai page | https://www.welingkar.org/programmes/full-time-programme-in-mumbai/pgdm |
| SIBM Pune | fee 2026-28 | SIBM fee structure 2026-28 | https://sibm.edu/mobile/assets/mobile/pdf/mbafee2026-28.pdf |
| SIBM Pune | median/average 2024-26 | SIBM CRP 2025 report | https://sibm.edu/mobile/assets/pdf/CRPReport2025.pdf |
| SIBM Pune | key dates | SIBM MBA important dates | https://sibm.edu/mba_importantdates |
| SIBM / SCMHRD | SNAP GE-PI weights (50/10/40) | SNAP official site | https://www.snaptest.org/blogs/whats-next-after-clearing-snap-ge-pi-structure-and-timelines |
| SCMHRD | fee 2026-28, intake, key dates | SCMHRD MBA programme page | https://scmhrd.edu/programmes/mba/ |
| SCMHRD | median/average 2024-26 | Final Placement Report 2024-26 | https://scmhrd.edu/wp-content/uploads/2026/08/final-placement-report-24-26.pdf |
| TISS Mumbai | intake, selection weights, CAT 2025 minimum percentiles | TISS CAT-PG Admission Brochure 2026-27 | https://tiss.ac.in/uploads/files/CAT_PG_Admission_Brochure_2026-2027-Ver3.pdf |
| TISS Mumbai | fee | MA HRM&LR admissions page | https://admissions.tiss.ac.in/view/10/admissions/ma-admissions/ma-in-human-resource-management-labour-relations/ |
| TISS Mumbai | median/mean 2024-26 | HRM&LR Final Placement Report 2026 | https://tiss.ac.in/uploads/files/TISS_HRM__LR_Final_Placement_Report_2026.pdf |
| PUMBA | first-year fee by category, exams | MBA admission instructions A.Y. 2026-27 | https://www.pumba.in/pdf/Instructions%20for%20Candidate%20seeking%20admission%20to%20MBA%20A.Y.2026-27_31072026.pdf |
| PUMBA | average 2022-24 | Placement Report 2022-24 (14 Oct 2024) | https://www.pumba.in/pdf/Placement%20Report%20(2022-24)_14102024.pdf |
| PUMBA | CAP 2026 Round I/IV closing scores | State CET Cell MBA 2026 portal | https://mba2026.mahacet.org.in/mba_26/home |
| IMI Delhi | fee 2025-27, intake | IMI Delhi Mandatory Disclosure | https://imiedu.s3.ap-south-1.amazonaws.com/uploads/1793358009954_file.pdf |
| IMI Delhi | median/average 2024-26 (PGDM) | Final Placement Report 2024-26 | https://imiedu.s3.ap-south-1.amazonaws.com/uploads/1793604435602_file.pdf |
| IMI Delhi | exams, selection, 2027 dates | PGDM admissions | https://admission.imi.edu/delhi/ |
| Great Lakes Chennai | fee 2026-28 | PGDM fee structure | https://www.greatlakes.edu.in/chennai/pgdm/fees |
| Great Lakes Chennai | exams, selection, 2027 dates | PGDM admissions | https://www.greatlakes.edu.in/chennai/pgdm/admissions |
| Great Lakes Chennai | average, Class of 2026 | PGDM placement report | https://www.greatlakes.edu.in/chennai/pgdm/placement-report |
| Great Lakes Chennai | intake | Mandatory Disclosure 2026 | https://www.greatlakes.edu.in/chennai/nba/Mandatory_Disclosure_2026.pdf |
| SJMSOM IIT Bombay | median/average 2024-26 | Final Placement Report 2024-26 | https://www.som.iitb.ac.in/wp-content/uploads/2016/07/Final-Placement-Report-2024-26.pdf |
| SJMSOM IIT Bombay | fee 2026-28 | Tuition and fees | https://www.som.iitb.ac.in/tuition-and-fees/ |
| SJMSOM IIT Bombay | weights, composite-score cutoffs | PI shortlisting / final evaluation criteria / composite score cut-off pages | https://www.som.iitb.ac.in/pi-shortlisting-criteria/ ; https://www.som.iitb.ac.in/final-eval-criteria/ ; https://www.som.iitb.ac.in/composite-score-cut-off/ |
| DMS IIT Delhi | fee (tuition), 2027 dates | MBA admission page | https://dms.iitd.ac.in/admission-mba/ |
| DMS IIT Delhi | median/average 2023-25 (MBA and MBA Telecom) | Final Placement Report 2023-25 | https://dms.iitd.ac.in/wp-content/uploads/2026/03/DMS-IIT-Delhi-Final-Placement-Report-2023-2025.pdf |
| DMS IIT Delhi | weights, shortlisting-index cutoffs 2026-28 | Shortlisting & Admission Criteria 2026-28 | https://dms.iitd.ac.in/wp-content/uploads/2017/08/Shortlisting-Criteria_2026_mba-Full-Time.pdf |

### Caveats and gaps
- **BIMM Pune:** almost entirely `null`. Its official domains (bimmpune.edu.in, sbup.edu.in) failed DNS resolution all session on 2026-11-11. Figures that appear only in search snippets were not used.
- **XLRI:** no median or average salary. The 2024-26 numbers are found only on news and aggregator sites, and xlri.ac.in renders its placement page with JavaScript. Intake, selection weights and cutoffs are not published.
- **Fees derived from per-year or per-semester figures:**
  - XLRI: about 15.3 L × 2.
  - NMIMS: 13.5 L × 2.
  - Welingkar: 7 L × 2, from the brochure. The live web page shows 7.5 L per year with no batch stated.
  - FMS: about ₹65,075 × 4 semesters.
- **First-year fee only:** JBIMS and PUMBA (`feeTotal: null`; category-wise amounts are in `feeNote`).
- **Fee not for the 2027-29 batch:**
  - IMI: fee is for 2025-27.
  - IIFT: fee is for 2026-28.
  - KJSIM: fee is for 2026-28.
  - DMS: the fee is tuition only.
- **Older salary data:**
  - DMS and IIFT: 2023-25.
  - Welingkar: 2023-25.
  - PUMBA: 2022-24, the latest report found.
- **Average only, no median (`medianSalary: null`):** IIFT, NMIMS, Great Lakes, PUMBA.
- **Median only:** KJSIM.
- **Intake:**
  - **NIRF all-programme figures:** MDI 570, IMT 510, JBIMS 190 (MMS alone is about 150-160 per its course page).
  - **SIBM intake is `null`:** SIBM's mobile page says 240 and its desktop page says 180.
  - **Not found:** DMS, SJMSOM, XLRI, PUMBA, BIMM.
- **Cutoffs:**
  - **Composite scores, not CAT percentiles:** SJMSOM (composite-score cutoffs) and DMS (shortlisting-index cutoffs). Their rows carry a `metric` note.
  - **Published by the State CET Cell, not the institute:** the JBIMS and PUMBA CAP cutoffs. The JBIMS cutoff file name says "2025_26" but the document is titled A.Y. 2026-27.
  - **Not published:** FMS, MDI, XLRI, IIFT, IMT, NMIMS, IMI and Great Lakes publish no cutoffs.
- **SNAP weights (SIBM, SCMHRD):** the 50/10/40 GE-PI weights come from the official SNAP site, not from the institutes' own pages.
