import { useMemo } from "react";
import { downloadJson } from "../lib/browser";
import { tokenizeJson, type JsonTokenType } from "../lib/jsonTokens";
import surface from "../styles/surface.module.css";
import { CopyButton } from "./CopyButton";
import { Icon } from "./Icon";
import styles from "./JsonView.module.css";

interface JsonViewProps {
  data: unknown;
  filename: string;
  title?: string;
}

const TOKEN_CLASS: Record<JsonTokenType, string | undefined> = {
  key: styles.key,
  string: styles.string,
  number: styles.number,
  boolean: styles.boolean,
  null: styles.null,
  punct: styles.punct,
  space: undefined,
};

export function JsonView({ data, filename, title = filename }: JsonViewProps) {
  const text = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const tokens = useMemo(() => tokenizeJson(text), [text]);

  return (
    <section className={styles.card} aria-labelledby="json-title">
      <header className={styles.head}>
        <h2 id="json-title" className={styles.title}>
          {title}
        </h2>
        <div className={styles.actions}>
          <CopyButton getText={() => text} />
          <button type="button" className={surface.button} onClick={() => downloadJson(filename, data)}>
            <Icon name="download" />
            Download
          </button>
        </div>
      </header>
      <pre className={styles.code} tabIndex={0} aria-label={`${title} source`}>
        <code>
          {tokens.map((t, i) =>
            t.type === "space" ? (
              t.text
            ) : (
              <span key={i} className={TOKEN_CLASS[t.type]}>
                {t.text}
              </span>
            ),
          )}
        </code>
      </pre>
    </section>
  );
}
