# Official FHIR R4 Validation

## Scope and result

The project's seven synthetic FHIR JSON samples were validated on **23 November 2026** with the **official HL7 FHIR Validator CLI 7.0.6** (build `86bf796ddc97`, built 13 November 2026), using **FHIR R4 version 4.0.1** and Java 17 inside a temporary Docker container on Windows.

**Result: 7/7 files processed successfully; 0 errors, 38 warnings and 24 informational notes.** The validator reported `Success: 0 errors` for every file. The warning count includes findings repeated when individual observations are also embedded in the Searchset Bundle.

| Sample | Errors | Warnings | Notes |
| --- | ---: | ---: | ---: |
| `blood_pressure.json` | 0 | 6 | 4 |
| `body_temp.json` | 0 | 4 | 2 |
| `heart_rate.json` | 0 | 3 | 2 |
| `medication_taken.json` | 0 | 2 | 0 |
| `searchset.json` | 0 | 17 | 14 |
| `spo2.json` | 0 | 3 | 2 |
| `symptom_score.json` | 0 | 3 | 0 |
| **Total** | **0** | **38** | **24** |

## Reproduce on Windows (Command Prompt)

From the project root, with Docker Desktop running:

```cmd
curl.exe -L --fail -o validator_cli.jar https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar

docker run --rm -v "%cd%:/work" -w /work eclipse-temurin:17-jre java -jar validator_cli.jar fhir-validation-samples -version 4.0.1 -tx n/a > fhir-validation-output.txt 2>&1

type fhir-validation-output.txt
```

The above download URL retrieves the **latest** validator and may produce different warnings in a future run. The recorded result used validator **7.0.6**. The sample directory can be regenerated using:

```cmd
python -m scripts.export_fhir_validation_samples
```

Do not regenerate samples if you want to reproduce the exact recorded sample contents without first checking for changes.

## Interpretation of warnings

- **Terminology validation unavailable:** `-tx n/a` deliberately disables a remote terminology server. The validator therefore could not fully verify some UCUM units (`mm[Hg]`, `Cel`, `/min`, `%`, `1`) or terminology value-set memberships.
- **FHIR best-practice recommendations:** Some observations lack narrative (`dom-6`) and/or a `performer` reference.
- **Profile guidance:** The validator notes applicable vital-sign profiles for heart rate, oxygen saturation, blood pressure and body temperature; these informational messages are not validation errors.

**Limitations:** Zero reported errors means the seven provided samples passed the checks performed in this run. It does **not** establish complete terminology validation, full conformance to all applicable vital-sign profiles, correctness of every runtime response, or clinical/regulatory certification.

