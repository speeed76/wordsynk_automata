# filename: utils/sanitize.py
import re
from typing import Optional

# Regex for basic UK postcode structure
POSTCODE_REGEX = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b", re.IGNORECASE)

# List of obvious non-phone number placeholders
INVALID_PHONE_PLACEHOLDERS = ["undefined", "null", "na", "n/a", "0"] # "0" is now explicitly invalid

def sanitize_postcode(raw: Optional[str]) -> Optional[str]:
    """
    Finds the first UK-like postcode in a string, formats it (uppercase, single space).
    Returns None if no postcode-like pattern is found.
    """
    if not raw:
        return None
    match = POSTCODE_REGEX.search(raw)
    if match:
        postcode = match.group(1).upper()
        # Insert space if missing before the last 3 chars (Inward code)
        if ' ' not in postcode and len(postcode) > 3:
            # Check if it looks like a standard format that needs a space
            if len(postcode) >= 5: # e.g., M11AA (5), SW1A0AA (7)
                 return f"{postcode[:-3]} {postcode[-3:]}"
            else: # Too short for typical format needing space (e.g. B11?)
                 return postcode
        elif ' ' in postcode:
            parts = postcode.split()
            parts = [part for part in parts if part] # Filter empty parts
            if len(parts) == 2:
                return f"{parts[0]} {parts[1]}"
            else: # Handle cases where split results in unexpected number of parts
                 return postcode.replace("  ", " ") # Basic multiple space cleanup
        else: # Already formatted or too short to need space
             return postcode
    return None

def validate_phone(raw: Optional[str]) -> Optional[str]:
    """
    Checks for obvious non-entries/placeholders for a phone number.
    Returns the cleaned string if it's not an obvious placeholder, otherwise None.
    This is lenient and aims to preserve potentially valid but oddly formatted numbers.
    """
    if raw is None:
        return None

    cleaned = raw.strip()

    # Check against obvious non-entries (case-insensitive for text)
    if not cleaned: # Empty string
        return None
    
    cleaned_lower = cleaned.lower()
    # Check against list of invalid placeholders
    if cleaned_lower in INVALID_PHONE_PLACEHOLDERS:
        return None
    
    # Specific check for short numbers that are just digits and likely placeholders
    if cleaned.isdigit() and len(cleaned) <= 4 and cleaned != "0": # Allow "0" to be caught by placeholder list only
        return None

    # Passed checks, return the cleaned string as potentially valid
    return cleaned