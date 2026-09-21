import React, { useEffect, useState } from "react";
import { request } from "./api";

function RuleCard({ rule, proposed = false }) {
  return (
    <article className={`rule-card${proposed ? " proposed" : " active"}`}>
      <div className="rule-card-heading">
        <h3>{rule.name}</h3>
        <span className={`rule-status ${rule.status.toLowerCase()}`}>
          {rule.status}
        </span>
      </div>
      <dl>
        <div>
          <dt>Timeframe</dt>
          <dd>{rule.timeframe}</dd>
        </div>
        {proposed ? (
          <>
            {rule.parameters && (
              <div>
                <dt>Parameters</dt>
                <dd>
                  EMA {rule.parameters.emas.join("/")} · source{" "}
                  {rule.parameters.source}
                </dd>
              </div>
            )}
            <div>
              <dt>Research concept</dt>
              <dd>{rule.hypothesis}</dd>
            </div>
            <div>
              <dt>Filtering</dt>
              <dd>{rule.filtering}</dd>
            </div>
            {rule.machine_definition && (
              <div>
                <dt>Exact machine definition</dt>
                <dd>{rule.machine_definition}</dd>
              </div>
            )}
            {rule.limitation && (
              <p className="rule-limitation">{rule.limitation}</p>
            )}
          </>
        ) : (
          <>
            <div>
              <dt>What it checks</dt>
              <dd>{rule.check}</dd>
            </div>
            {rule.configured_parameter && (
              <div>
                <dt>Current configured value</dt>
                <dd>{rule.configured_parameter}</dd>
              </div>
            )}
            <div>
              <dt>Implementation maturity</dt>
              <dd>{rule.implementation_stage}</dd>
            </div>
            <div>
              <dt>Affects</dt>
              <dd>{rule.affects}</dd>
            </div>
            <div>
              <dt>Why a candidate can fail</dt>
              <dd>{rule.why_can_fail}</dd>
            </div>
          </>
        )}
      </dl>
    </article>
  );
}

export default function Rules() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    request("/api/internal/strategy-lab/rules")
      .then(setCatalog)
      .catch((failure) => setError(failure.message));
  }, []);

  if (error)
    return (
      <p className="rules-error" role="alert">
        {error}
      </p>
    );
  if (!catalog) return <p role="status">Loading rules…</p>;

  return (
    <section className="rules-view" aria-labelledby="rules-title">
      <header className="rules-header">
        <h2 id="rules-title">Rules</h2>
        <p>
          Strategy: <strong>{catalog.strategy}</strong>
        </p>
        <p>
          This is an {catalog.strategy_maturity} strategy. ACTIVE below means a
          rule currently participates in FORMING_LONG / FORMING_SHORT. No rule
          here is an entry or trade instruction.
        </p>
      </header>

      <aside className="rules-lifecycle" aria-label="Rule status meanings">
        {Object.entries(catalog.lifecycle_definitions).map(
          ([status, meaning]) => (
            <p key={status}>
              <strong>{status}</strong> — {meaning}
            </p>
          ),
        )}
      </aside>

      <section aria-labelledby="active-rules-title">
        <h2 id="active-rules-title">Active Rules</h2>
        <p>
          These machine-defined checks currently contribute to FORMING
          decisions.
        </p>
        <div className="rules-grid">
          {catalog.active_rules.map((rule) => (
            <RuleCard key={rule.name} rule={rule} />
          ))}
        </div>
      </section>

      <section aria-labelledby="proposed-rules-title">
        <h2 id="proposed-rules-title">Research / Proposed Rules</h2>
        <p>These are hypotheses for research, not established trading facts.</p>
        <div className="rules-grid">
          {catalog.proposed_rules.map((rule, index) => (
            <RuleCard key={`${rule.name}-${index}`} rule={rule} proposed />
          ))}
        </div>
      </section>
    </section>
  );
}
