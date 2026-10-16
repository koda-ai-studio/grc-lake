# Framework Coverage Matrix

Generated from the control catalog + CCF safeguards — never hand-edited.
Regenerate with `make coverage-doc`. Mapping coverage measures catalog curation,
not operating effectiveness, assessment completion, or certification. API fields
retain `evaluatable` and `attestable` names for compatibility.

Framework packs: 20 with catalogued requirements (2 more registry entries planned or superseded)
Requirements catalogued: 2252 (all source-cited)
Mapped (touched by a safeguard): 1803 (80.1%)
Reviewed safeguard mappings: 1163 (51.6%), of which 381 are source-native self-maps and 782 are crosswalk-reviewed (34.7%); 339 rest only on legacy reviews with no recorded reviewer
Asset types modeled: 20

> `Source-cited` = the requirement has an official source link. `Mapped` = a safeguard claims it (reviewed or proposed). `Reviewed` = a human has confirmed the safeguard-to-requirement mapping. `Source-native self-maps` = requirements reviewed only through a safeguard that maps that one requirement and cites the framework's own pinned source (registry SHA-256); review confirms extraction fidelity, not a cross-framework judgement. `Crosswalk reviewed` = requirements with at least one reviewed mapping from a reusable or cross-framework safeguard. The blended total spans uneven frameworks; read coverage per row. `No recorded reviewer` = reviewed requirements whose only reviewed mappings predate decision receipts and name no reviewer (controls/reviews/legacy-unattributed.json). An assessment still needs scoped evidence and tests of operating effectiveness.

| Framework | Official source | Status | Requirements | Source-cited | Mapped | Reviewed mappings | Reviewed % | Source-native self-maps | Crosswalk reviewed | Crosswalk reviewed % | No recorded reviewer | Source state |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| CIS Critical Security Controls v8.1 (top-level coverage) | [Center for Internet Security - CIS Controls v8.1](https://www.cisecurity.org/controls/v8-1) | implemented_limited_mapping | 18 | 18 | 15 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | never pulled |
| CIS Amazon Web Services Foundations Benchmark | [CIS Amazon Web Services Foundations Benchmark v3.0.0](https://www.cisecurity.org/benchmark/amazon_web_services) | implemented_full_pack | 62 | 62 | 51 | 39 | 62.9% | 0 | 39 | 62.9% | 39 | never pulled |
| CMMC 2.0 Level 2 (NIST SP 800-171 alignment) | [DoD CMMC Program](https://dodcio.defense.gov/CMMC/Documentation/) | implemented_full_pack | 110 | 110 | 110 | 73 | 66.4% | 0 | 73 | 66.4% | 54 | never pulled |
| DORA - Digital Operational Resilience Act (EU) 2022/2554 | [EUR-Lex, Regulation (EU) 2022/2554 (CELEX 32022R2554)](https://eur-lex.europa.eu/eli/reg/2022/2554/oj) | implemented_limited_mapping | 99 | 99 | 79 | 79 | 79.8% | 0 | 79 | 79.8% | 0 | fresh |
| EU AI Act - Regulation (EU) 2024/1689 | [EUR-Lex - Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) | implemented_limited_mapping | 16 | 16 | 16 | 2 | 12.5% | 0 | 2 | 12.5% | 1 | never pulled |
| NIST SP 800-53B Moderate baseline (FedRAMP foundation only) | [NIST SP 800-53 Rev 5 Moderate baseline (FedRAMP Moderate foundation)](https://csrc.nist.gov/publications/detail/sp/800-53b/final) | implemented_full_pack | 287 | 287 | 262 | 114 | 39.7% | 0 | 114 | 39.7% | 96 | never pulled |
| GDPR - EU General Data Protection Regulation (2016/679) | [EUR-Lex - Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj) | implemented_limited_mapping | 20 | 20 | 20 | 2 | 10.0% | 0 | 2 | 10.0% | 2 | never pulled |
| HIPAA Security Rule (45 CFR Parts 160, 162, 164) | [U.S. HHS HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html) | implemented_limited_mapping | 24 | 24 | 19 | 4 | 16.7% | 0 | 4 | 16.7% | 4 | never pulled |
| ISO/IEC 27001:2022 Information security management systems | [ISO/IEC 27001:2022](https://www.iso.org/standard/27001) | implemented_full_pack | 93 | 93 | 81 | 17 | 18.3% | 0 | 17 | 18.3% | 10 | never pulled |
| ISO/IEC 27017:2015 Cloud security controls | [ISO/IEC 27017:2015](https://www.iso.org/standard/43757.html) | implemented_full_pack | 47 | 47 | 44 | 18 | 38.3% | 0 | 18 | 38.3% | 18 | never pulled |
| ISO/IEC 27701:2019 Privacy information management | [ISO/IEC 27701:2019](https://www.iso.org/standard/71670.html) | planned | 0 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | never pulled |
| ISO/IEC 27701:2025 Privacy information management | [ISO/IEC 27701:2025](https://www.iso.org/standard/27701) | implemented_limited_mapping | 10 | 10 | 8 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | fresh |
| ISO/IEC 42001:2023 AI management system | [ISO/IEC 42001:2023](https://www.iso.org/standard/42001) | implemented_full_pack | 40 | 40 | 37 | 14 | 35.0% | 0 | 14 | 35.0% | 9 | never pulled |
| NIS2 Directive (EU) 2022/2555 | [EUR-Lex, Directive (EU) 2022/2555 (CELEX 32022L2555)](https://eur-lex.europa.eu/eli/dir/2022/2555/oj) | implemented_limited_mapping | 17 | 17 | 17 | 17 | 100.0% | 0 | 17 | 100.0% | 0 | fresh |
| NIST SP 800-171 Rev 3 (Protecting CUI in Nonfederal Systems) | [NIST SP 800-171 Rev. 3 (OSCAL catalog, usnistgov/oscal-content)](https://csrc.nist.gov/pubs/sp/800/171/r3/final) | implemented_limited_mapping | 97 | 97 | 85 | 85 | 87.6% | 0 | 85 | 87.6% | 0 | fresh |
| NIST SP 800-53 Rev 5 Security and Privacy Controls | [NIST SP 800-53 Rev 5 (OSCAL catalog, usnistgov/oscal-content)](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final) | implemented_limited_mapping | 1014 | 1014 | 666 | 495 | 48.8% | 381 | 114 | 11.2% | 96 | fresh |
| NIST AI Risk Management Framework | [NIST Artificial Intelligence Risk Management Framework (AI RMF 1.0)](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10) | implemented_full_pack | 72 | 72 | 69 | 53 | 73.6% | 0 | 53 | 73.6% | 0 | never pulled |
| NIST Cybersecurity Framework (CSF) 2.0 | [NIST Cybersecurity Framework 2.0](https://www.nist.gov/cyberframework) | implemented_limited_mapping | 106 | 106 | 106 | 72 | 67.9% | 0 | 72 | 67.9% | 0 | never pulled |
| NIST Risk Management Framework (SP 800-37 Rev 2) | [NIST SP 800-37 Rev. 2](https://csrc.nist.gov/pubs/sp/800/37/r2/final) | implemented_limited_mapping | 47 | 47 | 46 | 46 | 97.9% | 0 | 46 | 97.9% | 0 | fresh |
| PCI DSS v4.0.1 Payment Card Industry Data Security Standard (top-level coverage) | [PCI Security Standards Council - PCI DSS v4.0.1](https://www.pcisecuritystandards.org/document_library/?category=pcidss) | implemented_limited_mapping | 12 | 12 | 11 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | never pulled |
| SOC 1 Type II (ICFR) | [AICPA SOC 1 Reporting on Controls at a Service Organization](https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2) | planned | 0 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | never pulled |
| SOC 2 Trust Services Criteria | [AICPA & CIMA 2017 Trust Services Criteria (With Revised Points of Focus - 2022)](https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022) | implemented_full_pack | 61 | 61 | 61 | 33 | 54.1% | 0 | 33 | 54.1% | 10 | never pulled |

## Control-To-Asset Applicability

Every seeded control declares the asset types it applies to. The pipeline joins those declarations into gold asset rows as `applicable_control_ids`.

| Asset type | Applicable controls |
| --- | ---: |
| `service` | 1789 |
| `audit_log` | 763 |
| `cloud_resource` | 650 |
| `cloud_policy` | 636 |
| `iam_role` | 405 |
| `identity_user` | 368 |
| `host` | 347 |
| `identity_group` | 342 |
| `okta_user` | 341 |
| `data_store` | 233 |
| `container_image` | 195 |
| `repo` | 193 |
| `ai_model` | 128 |
| `ai_agent` | 120 |
| `s3_bucket` | 69 |
| `identity_account` | 62 |
| `user` | 5 |
| `network` | 4 |
| `identity_role_assignment` | 3 |
| `account_config` | 1 |
