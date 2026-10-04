# Flood Demo: Hadera and Zeelim

This demo presents two real flood events using measurements from hydrometric stations: Nahal Hadera on January 8, 2013, and Nahal Zeelim on November 1, 2023. Its purpose is to show that the system can detect the beginning of an event according to the stream's flow regime, without waiting for extreme discharge levels.

## Detection logic

- In an ephemeral stream, a flood is confirmed after two consecutive measurements at or above 1 m³/s.
- In a perennial stream, classified by the system as `flowing_baseline`, a flood is confirmed after two consecutive measurements at or above the station's Q2 threshold.
- In both cases, the maximum permitted interval between the two measurements is 30 minutes.
- Q5, Q10, and the higher thresholds describe the event's severity after it has been confirmed; they are not detection conditions.

## Event 1: Nahal Hadera, January 8, 2013

### What happened

An exceptional rainstorm caused an extreme rise in Nahal Hadera. A planning document published by the Sharon Drainage and Streams Authority describes the event as producing the highest peak discharge recorded in the stream up to that time, with extensive flood damage, including damage at the Granot complex. Nahal Hadera overflowed its banks and flooded parts of the city. A report published at 21:06 stated that firefighters rescued dozens of residents from Tzahal Street using rubber boats and the roof of a fire engine. The following day, residents of Borochov Street reported that the contents of their homes had been almost completely destroyed. A flooded Israel Electric Corporation substation also left large parts of the city without power, although electricity had been restored to most residents by the following morning.

### Measurements used in the demo

The **Hadera – Gan Shmuel** station is classified as a perennial, or flowing-baseline, stream. Its Q2 threshold is 32 m³/s, and its Q5 threshold is 91 m³/s.

| Historical time | Discharge | Meaning in the system |
|---|---:|---|
| 11:09:45 | 66.14 m³/s | First measurement above Q2; not yet confirmed |
| 11:22:41 | 77.78 m³/s | Second consecutive measurement above Q2; flood confirmed |
| 11:44:01 | 92.15 m³/s | Q5 crossed; severity update for an already detected event |

The 11:09:45–11:22:41 pair is the first pair in the file that satisfies both the Q2 threshold and the 30-minute interval limit. The correct detection time for the demo is therefore **11:22:41**. There is no need to wait for Q10 to be crossed. The full series later records a peak discharge of 278.77 m³/s at 19:15:32, but this is a reconstructed data point and is therefore not used as a basis for detection in the demo.

### How the system could have helped

An alert at 11:22 would have provided an early and unambiguous indication that a perennial stream had transitioned from ordinary flow into a confirmed flood. The Q5 update approximately 21 minutes later would have indicated that the event was becoming more severe. This information could have supported inspections of nearby crossings and roads, preparation by rescue services, protection of infrastructure, and warnings to residents in low-lying areas.

The public report about the rescue of dozens of residents was published at 21:06, almost ten hours after the station-based detection time. However, no precise documented time is available for when floodwater first entered each affected street. The demo should therefore not be presented as proof that the city would have received almost ten hours of warning. It does show that Q2-based detection would have occurred much earlier than detection based on Q10 or the event's peak discharge.

## Event 2: Nahal Zeelim, November 1, 2023

### What happened

This was the first flood of the 2023–2024 hydrological year in Nahal Zeelim. According to the event record on `floods.org.il`, it was a significant flood that caused prolonged road closures. The first wave reached the road at 16:52, and the second wave arrived at 17:03. Real-time updates from live-streaming cameras enabled timely warnings to road users, including a warning for the second wave.

### Measurements used in the demo

Nahal Zeelim is classified as an ephemeral stream, so its detection threshold is 1 m³/s—not Q2.

| Historical time | Discharge | Meaning in the system |
|---|---:|---|
| 16:10:00 | 0.000 m³/s | Baseline condition with no flow |
| 16:17:54 | 3.835 m³/s | First measurement above 1 m³/s; not yet confirmed |
| 16:35:00 | 3.375 m³/s | Second consecutive measurement above 1 m³/s; flood confirmed |

The system would have generated an alert at **16:35**, exactly **17 minutes before** the first wave reached the road at 16:52. Later measurements, including the rise to 40.64 m³/s at 17:08:25, are not seeded into the demo. This ensures that detection is not based retrospectively on information that arrived after the first wave.

### How the system could have helped

A 17-minute window could allow warnings to be issued to drivers, preventive roadblocks to be placed, traffic control centers to be updated, and emergency services to be dispatched to the relevant crossing points. The event record states that cameras did help provide warnings. The proposed system adds an earlier automated detection layer based on station measurements, before the flood wave becomes visible on a camera near the road.

## How the events are represented in the demo

The detection engine accepts only recent observations. Historical records from 2013 and 2023 therefore cannot be submitted with their original dates and still pass the system's freshness checks. The demo moves the six selected measurements to times close to the demo run while preserving the exact intervals between them. The original historical dates and times appear in this document and in the scenario description.

The demo uses only measurements marked as **measured** in the source CSV files. It does not seed news reports or reported flood-wave arrival times as evidence for the detection engine. This avoids a circular setup in which the desired result is already present in the input. External sources are used only to compare the alert time with what subsequently happened in reality.

## Sources

- Hadera – Gan Shmuel station measurements: `0c63d2ce-636c-4814-8a73-98820b9f0450 (4).csv`.
- Zeelim station measurements: `צאלים 01.11.2023.csv`.
- [Sharon Drainage and Streams Authority — Nahal Hadera regulation plan](https://rnsharon.org.il/wp-content/uploads/2020/12/8-%D7%A7%D7%98%D7%A2-%D7%92%D7%91%D7%95%D7%9C-%D7%97%D7%93%D7%A8%D7%94-%D7%9E%D7%A4%D7%92%D7%A9-%D7%94%D7%AA%D7%A2%D7%9C%D7%95%D7%AA-%D7%AA%D7%95%D7%9B%D7%A0%D7%99%D7%AA-%D7%A4%D7%A8%D7%A1%D7%95%D7%9D-%D7%95%D7%94%D7%9B%D7%A8%D7%96%D7%94-%D7%9E%D7%A1-10514-1.pdf).
- [Walla — Dozens rescued from Tzahal Street in Hadera, January 8, 2013](https://news.walla.co.il/break/2604965).
- [Walla — Hadera residents return to damaged homes, January 9, 2013](https://www.walla.co.il/news/israel/2605190).
- [The Times of Israel — Rescues and power outage in Hadera, January 8, 2013](https://www.timesofisrael.com/as-waters-rise-air-force-rescue-team-extracts-15-people-stranded-on-a-roof/).
- [Flood Risk Portal — First flood in Nahal Zeelim, November 1, 2023](https://floods.org.il/%D7%A4%D7%95%D7%A8%D7%A1%D7%9D-%D7%9C%D7%90%D7%97%D7%A8%D7%95%D7%A0%D7%94-%D7%A9%D7%99%D7%98%D7%A4%D7%95%D7%9F-%D7%A8%D7%90%D7%A9%D7%95%D7%9F-%D7%91%D7%A0%D7%97%D7%9C-%D7%A6%D7%90%D7%9C%D7%99%D7%9D/).
