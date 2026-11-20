"""Pull the JSON object out of a model reply (code fences, stray text, control chars)."""
import re


def extract_json_object(output):
    """Extract the last complete JSON object from LLM output, handling streaming artifacts."""
    if not output:
        return None
    # Remove markdown code fences if present
    output = re.sub(r'```json\s*', '', output)
    output = re.sub(r'```\s*$', '', output)
    # Remove ANSI escape sequences
    output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', output)
    output = re.sub(r'\u001b\[[0-9;]*[A-Za-z]', '', output)
    # Remove other control characters
    output = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', output)
    # Find all JSON-like objects and return the last complete one
    # Use a stack-based approach to find balanced braces
    brace_stack = []
    json_candidates = []
    for i, ch in enumerate(output):
        if ch == '{':
            brace_stack.append(i)
        elif ch == '}' and brace_stack:
            start = brace_stack.pop()
            if not brace_stack:  # Complete object
                json_candidates.append(output[start:i+1])
    # Return the last (most complete) candidate
    return json_candidates[-1] if json_candidates else None
