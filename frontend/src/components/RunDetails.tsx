import type { RunSummary } from "../api/client";

export function RunDetails({ run }: { run: RunSummary }) {
  const cost =
    run.estimated_cost_usd !== null ? `$${run.estimated_cost_usd.toFixed(4)}` : "not applicable";
  return (
    <details className="run-details">
      <summary>About this result</summary>
      <dl>
        <dt>Provider</dt>
        <dd>{run.provider === "replay" ? "Saved response (replay)" : run.provider}</dd>
        <dt>Model</dt>
        <dd>{run.model}</dd>
        <dt>Prompt version</dt>
        <dd>{run.prompt_version}</dd>
        <dt>Effort</dt>
        <dd>{run.effort}</dd>
        <dt>Tokens in / out</dt>
        <dd>
          {run.input_tokens ?? "–"} / {run.output_tokens ?? "–"}
        </dd>
        <dt>Estimated cost</dt>
        <dd>{cost}</dd>
        <dt>Processing time</dt>
        <dd>{run.duration_ms !== null ? `${(run.duration_ms / 1000).toFixed(1)} s` : "–"}</dd>
      </dl>
    </details>
  );
}
