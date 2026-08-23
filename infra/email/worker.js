/**
 * Cloudflare Email Routing worker: forwards mail sent to any
 * u-<id>@APPLY_EMAIL_DOMAIN alias to Aptil's inbound webhook as signed JSON.
 *
 * The signature is HMAC-SHA256 over the exact bytes POSTed, using the same
 * secret as INBOUND_EMAIL_SECRET on the API. HTML is intentionally NOT
 * forwarded — only the plain-text part — so the API never stores or renders
 * foreign HTML.
 *
 * Bind in wrangler.toml:
 *   [vars] APTIL_WEBHOOK = "https://aptil.xyz/api/v1/inbound/email"
 *   secret: INBOUND_EMAIL_SECRET
 */
export default {
  async email(message, env) {
    const chunks = [];
    for await (const c of message.raw) chunks.push(c);
    const raw = new TextDecoder().decode(await new Blob(chunks).arrayBuffer());

    // Plain text only: strip anything between angle-bracket tags as a coarse
    // guard, and cap length so one huge mail cannot blow the request.
    const text = raw.replace(/<[^>]+>/g, " ").slice(0, 50000);

    const body = JSON.stringify({
      to: message.to,
      from: message.from,
      subject: message.headers.get("subject") || "",
      text,
    });

    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(env.INBOUND_EMAIL_SECRET),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const sigBuf = await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(body),
    );
    const sig = [...new Uint8Array(sigBuf)]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

    await fetch(env.APTIL_WEBHOOK, {
      method: "POST",
      headers: { "content-type": "application/json", "x-aptil-signature": sig },
      body,
    });
  },
};
