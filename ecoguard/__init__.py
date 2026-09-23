"""EcoGuard: watching Israel for fires, floods, earthquakes and air pollution.

The pipeline runs in one direction. Collectors fetch readings from outside
providers and store them. Detectors ask whether any reading is unusual.
The coordinator decides whether several unusual readings are one event or
several. Analyzers work out how bad that event is and what it threatens.
Planners say what should be done about it, and the resource allocator says who
should do it. The dashboard reads the result.
"""
