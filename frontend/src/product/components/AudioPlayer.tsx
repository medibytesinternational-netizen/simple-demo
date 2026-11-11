import type { AudioMeta } from "../api/types";
import type { AudioSource } from "../lib/files";
import { formatClock, formatDb, formatPercent } from "../lib/format";
import styles from "./AudioPlayer.module.css";


interface AudioPlayerProps {
  sources: readonly AudioSource[];
  audio: AudioMeta;
}

export function AudioPlayer({ sources, audio }: AudioPlayerProps) {
  const stats: [string, string][] = [
    ["Duration", formatClock(audio.duration_s)],
    ["Sample rate", `${(audio.sample_rate / 1000).toFixed(audio.sample_rate % 1000 === 0 ? 0 : 1)} kHz`],
    ["Speech", formatPercent(audio.vad_ratio)],
    ["SNR", formatDb(audio.snr_db)],
    [
      "Level",
      audio.rms_dbfs_before !== null && audio.rms_dbfs_after !== null
        ? `${audio.rms_dbfs_before.toFixed(1)} to ${audio.rms_dbfs_after.toFixed(1)} dBFS`
        : "",
    ],
  ];

  return (
    <section className={styles.card} aria-labelledby="audio-title">
      <h2 id="audio-title" className={styles.title}>
        Audio
      </h2>

      {sources.length === 0 ? (
        <p className={styles.empty}>No audio files were kept for this job.</p>
      ) : (
        <div className={styles.players}>
          {sources.map((s) => (
            <figure key={s.filename} className={styles.player}>
              <figcaption>
                <span className={styles.label}>{s.label}</span>
                <span className={styles.desc}>{s.description}</span>
              </figcaption>
              <audio controls preload="metadata" src={s.url} aria-label={s.label}>
                <a href={s.url}>Download {s.filename}</a>
              </audio>
              <a className={styles.link} href={s.url} download={s.filename}>
                Download {s.filename}
              </a>
            </figure>
          ))}
        </div>
      )}

      <dl className={styles.stats}>
        {stats
          .filter(([, value]) => value !== "")
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      <p className={styles.hash}>
        Input SHA-256 <span>{audio.input_sha256}</span>
      </p>
    </section>
  );
}
