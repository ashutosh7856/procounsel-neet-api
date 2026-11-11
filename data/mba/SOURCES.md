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
