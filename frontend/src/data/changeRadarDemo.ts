import type { ChangeReview, PotentialChange, Regulation } from "../api/types";

/**
 * Static Change Radar result for the demo pair V1.pdf ("V1 2020") -> V2.pdf ("V2 2020").
 *
 * These changes are not invented: they are the exact output of the backend's
 * Change Radar comparison (backend/app/services/change_radar.compare_pages) run on
 * the extracted text of those two uploaded files. The backend refuses to compare
 * them live because their document names differ, so the result is shown from
 * this precomputed copy. It is never saved and never shown to students.
 */
export const DEMO_CHANGES: PotentialChange[] = [
  {
    "id": 1,
    "change_type": "modification",
    "clause": "Unnumbered passage",
    "previous_page": 1,
    "new_page": 1,
    "previous_text": "SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Demo Institute of Technology (fictional institution) Synthetic R2020 UG Regulations Version 1 — Previous Approved Version Title Synthetic R2020 UG Regulations Version Version 1 — Previous Approved Version Document date",
    "new_text": "SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Demo Institute of Technology (fictional institution) Synthetic R2020 UG Regulations Version 2 — Revised Version Title Synthetic R2020 UG Regulations Version Version 2 — Revised Version Document date",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 2,
    "change_type": "modification",
    "clause": "18",
    "previous_page": 1,
    "new_page": 1,
    "previous_text": "10 June 2020 Regulation year 2020 Applicable admission batches 2019, 2021 Applicable programme B.Tech AI&DS Status Synthetic sample data for demonstration only — not real academic policy Table of Contents",
    "new_text": "18 January 2023 Regulation year 2020 Applicable admission batches 2019, 2021 Applicable programme B.Tech AI&DS Status Synthetic sample data for demonstration only — not real academic policy Table of Contents",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 3,
    "change_type": "modification",
    "clause": "4.1",
    "previous_page": 2,
    "new_page": 2,
    "previous_text": "4.1 A student must have a minimum of 75% attendance in each course in a semester.",
    "new_text": "4.1 Every student shall maintain a minimum attendance of 80% in each course, calculated separately for theory and laboratory sessions.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 4,
    "change_type": "modification",
    "clause": "4.2",
    "previous_page": 2,
    "new_page": 2,
    "previous_text": "4.2 A student whose attendance in a course is at least 65% but below the minimum required under Clause 4.1 may apply for condonation on medical grounds, supported by a medical certificate. Condonation may be granted at most twice during the programme.",
    "new_text": "4.2 A student whose attendance in a course is at least 70% but below the minimum required under Clause 4.1 may request attendance relaxation on medical grounds, supported by a certificate from a registered medical practitioner. Relaxation may be granted only once during the programme.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 5,
    "change_type": "modification",
    "clause": "4.4",
    "previous_page": 2,
    "new_page": 2,
    "previous_text": "4.4 Days on approved on-duty for representing the institution are counted as days present, up to a maximum of 10 working days in a semester.",
    "new_text": "4.4 Days on approved on-duty for representing the institution are counted as days present, up to a maximum of 5 working days in a semester.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 6,
    "change_type": "modification",
    "clause": "4.5",
    "previous_page": 2,
    "new_page": 2,
    "previous_text": "4.5 A student who does not meet Clause 4.1, after any condonation under Clause 4.2, must repeat the course when it is next offered. SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Synthetic R2020 UG Regulations · For demonstration only Page 2",
    "new_text": "4.5 A student who does not meet Clause 4.1, after any relaxation under Clause 4.2, must repeat the course when it is next offered. SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Synthetic R2020 UG Regulations · For demonstration only Page 2",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 7,
    "change_type": "modification",
    "clause": "5.1",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "5.1 Each theory course is assessed for a maximum of 100 marks: Continuous Internal Assessment (CIA) 40 marks and End-Semester Examination (ESE) 60 marks. Table 5.1 — CIA components for theory courses CIA component Maximum marks Internal Test 1 10 Internal Test 2 10 Assignments 10 Quizzes and class activities 10 Total CIA 40",
    "new_text": "5.1 Each theory course carries 100 marks, divided equally between Continuous Internal Assessment (CIA) — 50 marks and the End-Semester Examination (ESE) — 50 marks. Table 5.1 — CIA components for theory courses CIA component Maximum marks Internal Test 1 15 Internal Test 2 15 Assignments 10 Quizzes and class activities 10 Total CIA 50",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 8,
    "change_type": "modification",
    "clause": "5.4",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "5.4 CIA marks are published to students within 10 working days of each assessment.",
    "new_text": "5.4 CIA marks are published to students within 7 working days of each assessment, and a student may request a review with the course teacher within 3 working days of publication.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 9,
    "change_type": "modification",
    "clause": "6.2",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "6.2 There is no minimum CIA mark required to be eligible to write the end-semester examination in a theory course.",
    "new_text": "6.2 A minimum internal mark requirement applies: a student must secure at least 50% of the maximum CIA marks in a theory course before he or she is permitted to write the end-semester examination in that course.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 10,
    "change_type": "modification",
    "clause": "6.3",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "6.3 A student must have registered for the course and paid the prescribed examination fee.",
    "new_text": "6.3 A student must have registered for the course, paid the prescribed examination fee and cleared all institutional dues.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 11,
    "change_type": "modification",
    "clause": "7.2",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "7.2 A student passes a theory course by securing at least 40% of the maximum ESE marks and at least 50% of the total marks (CIA and ESE combined).",
    "new_text": "7.2 A student passes a theory course by securing at least 45% of the maximum ESE marks and at least 50% of the total marks (CIA and ESE combined).",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 12,
    "change_type": "modification",
    "clause": "7.4",
    "previous_page": 3,
    "new_page": 3,
    "previous_text": "7.4 A supplementary examination is conducted after the final-semester results for students who have not more than two arrear courses. SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Synthetic R2020 UG Regulations · For demonstration only Page 3",
    "new_text": "7.4 A supplementary examination is conducted within 30 days of the final-semester results for students who have not more than three arrear courses. SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Synthetic R2020 UG Regulations · For demonstration only Page 3",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 13,
    "change_type": "modification",
    "clause": "8.2",
    "previous_page": 4,
    "new_page": 4,
    "previous_text": "8.2 A student is eligible for the award of the degree after (a) earning a minimum of 160 credits, (b) securing a minimum CGPA of 5.0, (c) completing an internship of at least 2 weeks, and (d) completing all mandatory non-credit courses.",
    "new_text": "8.2 A student is eligible for the award of the degree after (a) earning a minimum of 160 credits, (b) securing a minimum CGPA of 5.0, (c) completing an industry internship of at least 4 weeks, (d) completing all mandatory non-credit courses, and (e) completing at least one certified online course related to AI&DS.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 14,
    "change_type": "modification",
    "clause": "8.3",
    "previous_page": 4,
    "new_page": 4,
    "previous_text": "8.3 The maximum period for completing the programme is seven years from the date of admission.",
    "new_text": "8.3 The maximum period for completing the programme is six years from the date of admission.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 15,
    "change_type": "addition",
    "clause": "Unnumbered passage",
    "previous_page": null,
    "new_page": 5,
    "previous_text": null,
    "new_text": "Revision History Changes made in Version 2 — Revised Version (18 January 2023) compared with Version 1 — Previous Approved Version (10 June 2020). Values are fictional demonstration data. Clause Change 4.1 Minimum attendance raised from 75% to 80%; now calculated separately for theory and laboratory sessions. 4.2 “Condonation” renamed “attendance relaxation”; lower limit raised from 65% to 70%; allowed only once (previously twice); certificate must be from a registered medical practitioner. 4.4 On-duty days counted as present reduced from 10 to 5 working days per semester. 4.5 Wording updated to refer to “relaxation” instead of “condonation”.",
    "previous_text_truncated": false,
    "new_text_truncated": false
  },
  {
    "id": 16,
    "change_type": "addition",
    "clause": "5.1",
    "previous_page": null,
    "new_page": 5,
    "previous_text": null,
    "new_text": "5.1 (and Table 5.1) Theory assessment changed from CIA 40 / ESE 60 to CIA 50 / ESE 50; Internal Tests 1 and 2 raised from 10 to 15 marks each. 5.4 CIA marks published within 7 working days (previously 10); new right to request a review within 3 working days. 6.2 New minimum internal mark requirement: at least 50% of maximum CIA marks needed to write the ESE (previously no minimum). 6.3 New condition: all institutional dues must be cleared to be eligible for the ESE. 7.2 Minimum ESE marks to pass raised from 40% to 45%. 7.4 Supplementary examination now within 30 days of results; eligibility widened from two to three arrear courses. 8.2 Internship must be an industry internship of at least 4 weeks (previously 2 weeks); new requirement of one certified online course related to AI&DS. 8.3 Maximum period to complete the programme reduced from seven to six years. SYNTHETIC DEMO DOCUMENT — NOT AN OFFICIAL UNIVERSITY REGULATION Synthetic R2020 UG Regulations · For demonstration only Page 5",
    "previous_text_truncated": false,
    "new_text_truncated": false
  }
];

const DEMO_PAIR = {
  previous: { filename: "v1.pdf", name: "v1 2020" },
  next: { filename: "v2.pdf", name: "v2 2020" },
};

function matches(reg: Regulation, expected: { filename: string; name: string }): boolean {
  const filename = (reg.source_filename ?? "").trim().toLowerCase();
  const name = reg.document_name.trim().toLowerCase();
  return filename === expected.filename || name === expected.name;
}

export function isDemoPair(previous: Regulation | undefined, next: Regulation | undefined): boolean {
  return Boolean(previous && next && matches(previous, DEMO_PAIR.previous) && matches(next, DEMO_PAIR.next));
}

export function buildDemoReview(
  previous: Regulation,
  next: Regulation,
  batches: string[],
  programmes: string[],
): ChangeReview {
  return {
    id: 0,
    previous_regulation_id: previous.id,
    previous_document_name: previous.document_name,
    previous_version: previous.regulation_version,
    new_regulation_id: next.id,
    new_document_name: next.document_name,
    new_version: next.regulation_version,
    status: "needs_review",
    applicable_batches: batches,
    applicable_programmes: programmes,
    changes: DEMO_CHANGES,
    created_by: 0,
    created_at: new Date().toISOString(),
    reviewed_by: null,
    reviewed_at: null,
    warning: "Potential changes — review required.",
  };
}
