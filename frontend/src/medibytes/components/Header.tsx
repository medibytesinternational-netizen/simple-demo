import { Icon } from "./Icon";
import styles from "./Header.module.css";

export function Header() {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <span className={styles.logo} aria-hidden="true">
          <Icon name="pulse" size={22} />
        </span>
        <div className={styles.titles}>
          <h1 className={styles.name}>MediBytes</h1>
          <p className={styles.subtitle}>Dictation to discharge note</p>
        </div>
      </div>
    </header>
  );
}
