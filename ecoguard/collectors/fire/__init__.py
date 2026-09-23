"""Sources collected because something might be burning.

Grouped by hazard rather than by provider, so "what feeds fire detection" is a
directory listing. The cost of that choice is visible next door in shared/:
weather belongs to no single hazard and had to go somewhere else.

Each subpackage is one source, holding its collector and whatever provider
client only it uses.
"""
