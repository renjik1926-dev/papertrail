export function PrivacyNotice({ onAck }: { onAck: () => void }) {
  return (
    <section className="privacy" aria-labelledby="privacy-title">
      <h2 id="privacy-title">Before you upload</h2>
      <ul>
        <li>Your letters stay on this computer.</li>
        <li>
          To read a letter, PaperTrail sends its text to Anthropic's API (the Claude AI model).
        </li>
        <li>Nothing is uploaded anywhere else: no analytics, no tracking.</li>
        <li>This is not legal, medical or financial advice. Check each item against the letter.</li>
      </ul>
      <button type="button" className="primary" onClick={onAck}>
        Got it
      </button>
    </section>
  );
}

export function DemoBanner() {
  return (
    <p className="banner" role="note">
      Demo with synthetic sample letters — results were processed ahead of time from saved Claude
      Haiku answers, so nothing is sent anywhere.
    </p>
  );
}
