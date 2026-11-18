"""Single source of truth for documentation types.

The feedback loop stores correction patterns under a doc type and the Doc
Writer looks them up by doc type, so both must classify a path identically.
"""


def classify_doc(path: str) -> str:
    p = path.lower()
    if "readme" in p:   return "readme"
    if "api" in p:      return "api_reference"
    if "auth" in p:     return "authentication"
    if "config" in p:   return "configuration"
    if "guide" in p:    return "guide"
    if "deploy" in p:   return "deployment"
    if "change" in p:   return "changelog"
    return "general"
