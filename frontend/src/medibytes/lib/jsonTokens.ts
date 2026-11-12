export type JsonTokenType = "key" | "string" | "number" | "boolean" | "null" | "punct" | "space";

export interface JsonToken {
  type: JsonTokenType;
  text: string;
}

// Sticky regex: each alternative is anchored at lastIndex.
const TOKEN =
  /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false)|(null)|([{}[\],:])|(\s+)/y;

/**
 * Tokenise JSON text (typically from JSON.stringify) for syntax colouring.
 * Unrecognised characters are emitted as punctuation so the text round-trips unchanged.
 */
export function tokenizeJson(source: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  let index = 0;
  while (index < source.length) {
    TOKEN.lastIndex = index;
    const m = TOKEN.exec(source);
    if (!m || m[0].length === 0) {
      tokens.push({ type: "punct", text: source.charAt(index) });
      index += 1;
      continue;
    }
    const [whole, str, colon, num, bool, nul, punct, space] = m;
    if (str !== undefined) {
      tokens.push({ type: colon !== undefined ? "key" : "string", text: str });
      if (colon !== undefined) tokens.push({ type: "punct", text: colon });
    } else if (num !== undefined) tokens.push({ type: "number", text: num });
    else if (bool !== undefined) tokens.push({ type: "boolean", text: bool });
    else if (nul !== undefined) tokens.push({ type: "null", text: nul });
    else if (punct !== undefined) tokens.push({ type: "punct", text: punct });
    else if (space !== undefined) tokens.push({ type: "space", text: space });
    index += whole.length;
  }
  return tokens;
}
