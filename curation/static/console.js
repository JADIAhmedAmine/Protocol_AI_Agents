"use strict";
const $ = (selector) => document.querySelector(selector);
const state = {kb: "", token: "", me: null, view: "claims", offset: 0, next: null, demo: null, search: "", epoch: 0};
const labels = {claims: ["Knowledge library", "Follow a claim from its first source to its latest decision."], reviews: ["Review queue", "Inspect current rounds and resolve decisions that need an operator."], agents: ["Agent registry", "See who contributes, reviews, and administers this knowledge base."]};
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function badge(value) { return node("span", value.replaceAll("_", " "), `badge ${value}`); }
function notify(message, failure = false) { const el = $("#notice"); el.textContent = message; el.className = `notice${failure ? " failure" : ""}`; el.hidden = false; }
function date(value) { return new Date(value * 1000).toLocaleString(); }
async function api(route, body, session = state) {
  const response = await fetch(`/v1/knowledge-bases/${encodeURIComponent(session.kb)}/${route}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: {Authorization: `Bearer ${session.token}`, "Content-Type": "application/json", ...(body !== undefined ? {"Idempotency-Key": crypto.randomUUID()} : {})},
    ...(body !== undefined ? {body: JSON.stringify(body)} : {})
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function button(text, action, className = "button") { const el = node("button", text, className); el.type = "button"; el.onclick = () => Promise.resolve().then(action).catch(e => notify(e.message, true)); return el; }
function empty(text) { $("#list").append(node("div", text, "empty")); }
function claimCard(claim, review) {
  const card = node("article", undefined, "claim-card");
  const left = node("div"); left.append(node("span", claim.topic, "topic"), node("h3", claim.text));
  left.append(node("div", review ? `${review.phase} · ${review.commitment_count} commitments · ${review.reveal_count} reveals` : `By ${claim.contributor} · ${date(claim.created_at)}`, "card-meta"));
  if (claim.frozen) left.append(node("div", "Frozen · operator review required", "card-meta"));
  const right = node("div", undefined, "card-side"); right.append(badge(review?.phase || claim.state), button("Inspect ↗", () => detail(claim.id)));
  card.append(left, right); return card;
}
async function refresh() {
  if (!state.me) return;
  const epoch = ++state.epoch;
  const session = {kb: state.kb, token: state.token};
  const view = state.view;
  $("#refresh").disabled = true;
  try {
    let result;
    if (view === "claims") {
      result = state.search ? await api("query", {text: state.search}, session) : await api(`claims?limit=12&offset=${state.offset}&state=${encodeURIComponent($("#state-filter").value)}`, undefined, session);
    } else result = await api(view === "reviews" ? "review-rounds" : "agents", undefined, session);
    let claims;
    if (view === "reviews") claims = await Promise.all(result.items.map(r => api(`claims/${r.claim_id}`, undefined, session)));
    if (epoch !== state.epoch) return;
    $("#list").replaceChildren();
    state.next = result.next_offset ?? null;
    $("#filters").hidden = view !== "claims";
    $(".pagination").hidden = view !== "claims" || !!state.search;
    $("#previous").disabled = state.offset === 0; $("#next").disabled = state.next === null;
    if (view === "claims") {
      $("#results-meta").textContent = state.search ? `${result.items.length} accepted matches · literal substring search · maximum 100` : `${result.total} claims · showing ${result.items.length ? state.offset + 1 : 0}–${state.offset + result.items.length}`;
      result.items.forEach(c => $("#list").append(claimCard(c)));
    } else if (view === "reviews") {
      $("#results-meta").textContent = `${result.items.length} open rounds visible to ${state.me.id} · refresh to update deadlines`;
      result.items.forEach((r, i) => $("#list").append(claimCard(claims[i], r)));
    } else {
      $("#results-meta").textContent = `${result.items.length} enrolled agents · fixed weights, no learned reputation`;
      result.items.forEach(agent => { const card = node("article", undefined, "claim-card"); const left = node("div"); left.append(node("h3", agent.id), node("div", agent.model, "card-meta")); card.append(left, badge(agent.role), node("span", `Weight ${agent.weight}`, "card-meta")); $("#list").append(card); });
    }
    if (!result.items.length) empty(view === "reviews" ? "No open rounds for this identity. Submit a claim or connect as an operator." : "Nothing here yet. Try another filter or submit a sourced claim.");
  } finally { if (epoch === state.epoch) $("#refresh").disabled = false; }
}
function section(title) { const el = node("section", undefined, "detail-section"); el.append(node("h3", title)); return el; }
function field(form, label, name, options) { const wrapper = node("label", label); let control; if (options) { control = node("select"); options.forEach(([v, t]) => { const o = node("option", t); o.value = v; control.append(o); }); } else { control = node("textarea"); control.rows = 3; control.maxLength = 10000; } control.name = name; control.required = true; wrapper.append(control); form.append(wrapper); }
function actionForm(parent, title, fields, route) {
  const area = section(title), form = node("form");
  fields.forEach(f => field(form, ...f));
  const error = node("p", "", "error"); error.setAttribute("role", "alert");
  const submit = node("button", title, "button primary"); submit.type = "submit"; form.append(error, submit);
  form.onsubmit = async e => { e.preventDefault(); submit.disabled = true; error.textContent = ""; try { await api(route, Object.fromEntries(new FormData(form))); $("#detail-dialog").close(); notify("Decision recorded in the audit history."); await refresh(); } catch (err) { error.textContent = err.message; } finally { submit.disabled = false; } };
  area.append(form); parent.append(area);
}
async function detail(id) {
  const epoch = state.epoch;
  const session = {kb: state.kb, token: state.token};
  const claim = await api(`claims/${id}`, undefined, session);
  const [review, events] = await Promise.all([api(`review-rounds/${claim.round_id}`, undefined, session), api(`claims/${id}/events`, undefined, session)]);
  if (epoch !== state.epoch) return;
  const root = $("#detail-content"); root.replaceChildren();
  root.append(badge(claim.state), node("h2", claim.text, "detail-title"), node("div", `Claim ${claim.id}\nRevision ${claim.revision}`, "identifier"));
  const source = section("Source & provenance");
  const link = node("a", claim.source.url); const parsed = new URL(claim.source.url); if (["https:", "http:"].includes(parsed.protocol)) { link.href = parsed.href; link.target = "_blank"; link.rel = "noopener noreferrer"; }
  source.append(link, node("blockquote", claim.source.passage), node("p", "Source verification: unverified. Sample sources and ballots may be synthetic.", "hint")); root.append(source);
  const round = section("Current review"); round.append(badge(review.phase));
  const facts = node("div", undefined, "fact-grid");
  for (const [name, value] of [["Commitments", review.commitment_count], ["Reveals", review.reveal_count], ["Required votes", review.policy.quorum]]) { const fact = node("div"); fact.append(node("span", name), node("strong", String(value))); facts.append(fact); }
  round.append(facts, node("p", `Policy ${review.policy.version} · ${review.policy.weighting}`, "hint"));
  if (review.deadlines[review.phase]) round.append(node("p", `Phase deadline: ${date(review.deadlines[review.phase])}`, "hint"));
  round.append(node("p", "Enrolled reviewers: " + (Object.keys(review.reviewers).join(", ") || "none — deadline will escalate to arbitration"), "hint"));
  if (review.result) round.append(node("pre", JSON.stringify(review.result, null, 2)));
  if (review.resolution) { round.append(node("h3", "Operator resolution"), node("pre", JSON.stringify(review.resolution, null, 2))); }
  round.append(button("Refresh record", () => detail(id))); root.append(round);
  const argumentsSection = section("Deliberation");
  review.arguments.forEach(a => { argumentsSection.append(node("h4", a.reviewer), node("blockquote", a.text)); });
  if (!review.arguments.length) argumentsSection.append(node("p", "No arguments recorded.", "hint"));
  root.append(argumentsSection);
  if (review.ballots) { const ballots = section("Disclosed ballots"); ballots.append(node("pre", JSON.stringify(review.ballots, null, 2))); root.append(ballots); }
  else root.append(node("p", "Ballot choices are concealed until the reveal period closes.", "hint"));
  if (review.phase === "arbitration" && state.me.role === "admin") actionForm(root, "Record resolution", [["Outcome", "outcome", [["active", "Accept / uphold"], ["retracted", "Retract"]]], ["Rationale", "rationale"]], `review-rounds/${review.id}/resolution`);
  if (claim.state === "active" && !claim.frozen && claim.dispute_count < 3 && ["admin", "reviewer"].includes(state.me.role)) actionForm(root, "File dispute", [["Reason", "reason"], ["New evidence", "evidence"]], `claims/${id}/disputes`);
  const audit = section("Audit trail"); const timeline = node("div", undefined, "timeline");
  events.items.forEach(event => { const item = node("div", undefined, "timeline-item"); item.append(node("strong", event.action.replaceAll("_", " ")), node("small", `${event.actor} · ${date(event.at)}`)); const disclosure = node("details"); disclosure.append(node("summary", "Event details"), node("pre", JSON.stringify(event, null, 2))); item.append(disclosure); timeline.append(item); });
  audit.append(timeline); root.append(audit);
  if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
}
function connectDialog() { $("#connect-error").textContent = ""; $("#connect-dialog").showModal(); }
$("#connection-button").onclick = connectDialog; $("#welcome-connect").onclick = connectDialog;
document.querySelectorAll("[data-close]").forEach(el => { el.onclick = () => document.getElementById(el.dataset.close).close(); });
$("#connect-form").onsubmit = async e => { e.preventDefault(); const submit = e.submitter; submit.disabled = true; try { const session = {kb: $("#kb").value.trim(), token: $("#token").value.trim()}; const me = await api("me", undefined, session); Object.assign(state, session, {me, offset: 0, search: ""}); $("#search").value = ""; $("#workspace-name").textContent = state.kb; $("#identity").textContent = `${me.id} · ${me.role}`; $("#connection-button").textContent = "Switch identity"; $("#welcome").hidden = true; $("#content").hidden = false; $("#new-claim").disabled = false; $("#connect-dialog").close(); $("#notice").hidden = true; await refresh(); } catch (err) { $("#connect-error").textContent = err.message; notify(err.message, true); } finally { submit.disabled = false; } };
$("#credentials-file").onchange = async e => { try { const file = e.target.files[0]; if (!file) return; if (file.size > 65536) throw new Error("Credentials file is too large."); const data = JSON.parse(await file.text()); if (typeof data.kb !== "string" || !/^[A-Za-z0-9_-]+$/.test(data.kb) || !data.tokens || typeof data.tokens !== "object" || !Object.values(data.tokens).length || !Object.values(data.tokens).every(t => typeof t === "string")) throw new Error("Expected a knowledge base and agent token map from curation.seed."); state.demo = data; $("#kb").value = data.kb; const select = $("#demo-identity"); select.replaceChildren(); Object.keys(data.tokens).forEach(id => { const option = node("option", id); option.value = id; select.append(option); }); if (Object.hasOwn(data.tokens, "operator")) select.value = "operator"; $("#identity-picker").hidden = false; select.onchange(); $("#connect-error").textContent = ""; } catch (err) { $("#connect-error").textContent = err.message; } };
$("#demo-identity").onchange = () => { $("#token").value = state.demo.tokens[$("#demo-identity").value]; };
$("#disconnect").onclick = () => { state.epoch++; Object.assign(state, {kb: "", token: "", me: null, demo: null}); $("#connect-form").reset(); $("#identity-picker").hidden = true; $("#demo-identity").replaceChildren(); $("#connect-dialog").close(); $("#workspace-name").textContent = "Not connected"; $("#identity").textContent = "No active identity"; $("#connection-button").textContent = "Connect"; $("#content").hidden = true; $("#welcome").hidden = false; $("#new-claim").disabled = true; $("#list").replaceChildren(); $("#detail-content").replaceChildren(); $("#notice").hidden = true; };
document.querySelectorAll("[data-view]").forEach(el => { el.onclick = () => { state.view = el.dataset.view; state.offset = 0; document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("selected", b === el)); $("#page-title").textContent = labels[state.view][0]; $("#page-subtitle").textContent = labels[state.view][1]; refresh().catch(e => notify(e.message, true)); }; });
$("#refresh").onclick = () => refresh().catch(e => notify(e.message, true));
$("#previous").onclick = () => { state.offset = Math.max(0, state.offset - 12); refresh().catch(e => notify(e.message, true)); };
$("#next").onclick = () => { state.offset = state.next ?? 0; refresh().catch(e => notify(e.message, true)); };
$("#state-filter").onchange = () => { state.offset = 0; state.search = ""; $("#search").value = ""; refresh().catch(e => notify(e.message, true)); };
$("#search-form").onsubmit = e => { e.preventDefault(); state.search = $("#search").value.trim(); state.offset = 0; refresh().catch(e => notify(e.message, true)); };
$("#new-claim").onclick = () => { $("#submit-error").textContent = ""; $("#submit-dialog").showModal(); };
$("#submit-form").onsubmit = async e => { e.preventDefault(); const submit = e.submitter; submit.disabled = true; try { const values = Object.fromEntries(new FormData(e.target)); const claim = await api("claims", {text: values.text, topic: values.topic, source: {url: values.url, passage: values.passage}}); e.target.reset(); $("#submit-dialog").close(); notify("Claim submitted. Its review round is open."); await refresh(); await detail(claim.id); } catch (err) { $("#submit-error").textContent = err.message; } finally { submit.disabled = false; } };
