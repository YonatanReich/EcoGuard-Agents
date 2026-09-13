# Fire Risk Strong-Event Case Study

These Tier B cases are independent qualitative event checks. They were not used to fit the model, calibration, thresholds, or model selection. Results indicate face validity or qualitative consistency only—not accuracy, recall, sensitivity, or statistical validation.

## Coverage

- Tier B events discovered: 10
- Complete feature vectors: 10
- Incomplete: 0
- LOW / MEDIUM / HIGH: 2 / 4 / 4
- MEDIUM+HIGH: 8 (80.0%)
- Mean / median score: 0.407 / 0.430

## Events

| Event | Reference time | Source | Location | Coordinate precision | Completeness | Score | Level | Notes |
|---|---|---|---|---|---|---:|---|---|
| wildfire_gt_18b074f033422e32a6f97245 | 2024-06-01T10:04:00+00:00 | israel_nature_and_parks_authority (official_report) | שמורת טבע מורדות נפתלי | geocoded_area_name_reference_not_exact_event_point | complete | 0.365 | MEDIUM | matched_firms_acquisition_for_date_only_event; slope_degrees, humidity_3h_before, temperature_12h_before |
| wildfire_gt_3aa97a6b256211f36cfce2b9 | 2024-07-04T11:25:00+00:00 | israel_nature_and_parks_authority (official_report) | שמורת טבע גמלא | geocoded_area_name_reference_not_exact_event_point | complete | 0.545 | HIGH | matched_firms_acquisition_for_date_only_event; days_since_previous_firms_candidate_within_10km, cos_hour, humidity_3h_before |
| wildfire_gt_9b431a239913e52f52c2b369 | 2024-07-06T10:47:00+00:00 | israel_nature_and_parks_authority (official_report) | שמורת טבע הארבל | geocoded_area_name_reference_not_exact_event_point | complete | 0.328 | MEDIUM | matched_firms_acquisition_for_date_only_event; days_since_previous_firms_candidate_within_10km, fires_within_10km_previous_90d, slope_degrees |
| wildfire_gt_07d74d68a7c3a4a89c1cced7 | 2024-07-21T10:15:00+00:00 | israel_nature_and_parks_authority (official_report) | שמורת טבע נחל החרמון בניאס | geocoded_area_name_reference_not_exact_event_point | complete | 0.557 | HIGH | matched_firms_acquisition_for_date_only_event; fires_within_10km_previous_90d, slope_degrees, humidity_3h_before |
| wildfire_gt_3dbacf0865cd119ccfb4c758 | 2024-07-21T10:15:00+00:00 | israel_nature_and_parks_authority (official_report) | צומת הטנק | geocoded_area_name_reference_not_exact_event_point | complete | 0.561 | HIGH | matched_firms_acquisition_for_date_only_event; fires_within_10km_previous_90d, slope_degrees, humidity_3h_before |
| wildfire_gt_6b08c7df4d7c78df00ad3964 | 2024-07-21T10:15:00+00:00 | israel_nature_and_parks_authority (official_report) | קיבוץ שניר | geocoded_locality_reference_not_exact_event_point | complete | 0.549 | HIGH | matched_firms_acquisition_for_date_only_event; fires_within_10km_previous_90d, humidity_3h_before, humidity_1h_before |
| wildfire_gt_ecca306e91c7deb13531c410 | 2025-04-30T10:11:00+00:00 | kkl_jnf_and_government_emergency_information (official_report) | יער אשתאול והרי ירושלים | geocoded_area_name_reference_not_exact_event_point | complete | 0.430 | MEDIUM | matched_firms_acquisition_for_date_only_event; days_since_previous_firms_candidate_within_10km, fires_within_10km_previous_90d, humidity_3h_before |
| wildfire_gt_2869a8062ef891f12068e67f | 2025-05-03T10:02:00+00:00 | israel_ministry_of_education (official_report) | יער מודיעין ליד מחלף ענבה | geocoded_area_name_reference_not_exact_event_point | complete | 0.252 | LOW | matched_firms_acquisition_for_date_only_event; days_since_previous_firms_candidate_within_10km, fires_within_10km_previous_90d, humidity_3h_before |
| telegram_police_362 | 2025-08-24T11:28:02+00:00 | דוברות משטרת ישראל (verified_telegram) | חורש סמוך ליישוב מבשרת ציון | geocoded_locality_reference_not_exact_event_point | complete | 0.430 | MEDIUM | source_event_timestamp; days_since_previous_firms_candidate_within_10km, cos_hour, slope_degrees |
| telegram_police_4286 | 2026-07-18T12:14:33+00:00 | דוברות משטרת ישראל (verified_telegram) | שטח פתוח סמוך ליישוב שמשית בעמק יזרעאל | geocoded_locality_reference_not_exact_event_point | complete | 0.049 | LOW | source_event_timestamp; cos_hour, humidity_3h_before, humidity_1h_before |

## Pre-event trajectories

Trajectories are limited to the two minute-precision Telegram events. Every T-12h/T-6h/T-3h vector is rebuilt as of that timestamp; the event-reference row is the already reconstructed T0 vector. Date-only official reports are excluded.

| Event | Offset | Evaluation time | Score | Level |
|---|---:|---|---:|---|
| telegram_police_362 | -12h | 2025-08-23T23:28:02+00:00 | 0.372 | MEDIUM |
| telegram_police_362 | -6h | 2025-08-24T05:28:02+00:00 | 0.147 | LOW |
| telegram_police_362 | -3h | 2025-08-24T08:28:02+00:00 | 0.159 | LOW |
| telegram_police_362 | 0h | 2025-08-24T11:28:02+00:00 | 0.430 | MEDIUM |
| telegram_police_4286 | -12h | 2026-07-18T00:14:33+00:00 | 0.147 | LOW |
| telegram_police_4286 | -6h | 2026-07-18T06:14:33+00:00 | 0.112 | LOW |
| telegram_police_4286 | -3h | 2026-07-18T09:14:33+00:00 | 0.331 | MEDIUM |
| telegram_police_4286 | 0h | 2026-07-18T12:14:33+00:00 | 0.049 | LOW |

## Interpretation limitations

Date-only official reports use the retained nearest qualifying FIRMS candidate acquisition time as the evaluation reference. This is explicit and does not upgrade source timestamp precision. That candidate is excluded from historical FIRMS-density features. Coordinates are geocoded area/locality references, not verified ignition points. Weather uses UTC observations strictly before each reference time. No post-event FIRMS observation is used as prior-fire context.
