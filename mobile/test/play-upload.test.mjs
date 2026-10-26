// scripts/play-upload.sh against a stand-in for Google's sign-in and Play's API: the signed sign-in
// request, the upload and the internal-track release, in order.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { generateKeyPairSync, createVerify } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("../scripts/play-upload.sh", import.meta.url));

test("uploads the bundle and releases it to internal testing with the notes", async () => {
  // A throwaway key made for this test only.
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const seen = [];
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const body = Buffer.concat(chunks);
      seen.push({ method: req.method, url: req.url, auth: req.headers.authorization, body });
      res.setHeader("Content-Type", "application/json");
      if (req.url === "/token") return res.end(JSON.stringify({ access_token: "tok" }));
      if (req.url.endsWith("/edits")) return res.end(JSON.stringify({ id: "e1" }));
      if (req.url.includes("/bundles")) return res.end(JSON.stringify({ versionCode: 98 }));
      res.end("{}");
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const root = `http://127.0.0.1:${server.address().port}`;
  const dir = mkdtempSync(join(tmpdir(), "play-upload-"));
  const aab = join(dir, "app.aab");
  writeFileSync(aab, "bundle bytes");
  const account = JSON.stringify({
    client_email: "uploader@example.iam.gserviceaccount.com",
    private_key: privateKey.export({ type: "pkcs8", format: "pem" }),
    token_uri: `${root}/token`,
  });
  try {
    await new Promise((resolve, reject) =>
      execFile("bash", [script, aab], {
        env: { ...process.env, PLAY_SERVICE_ACCOUNT_JSON: account, PLAY_PACKAGE: "com.example.app",
               PLAY_NOTES: "RouteMaker v1.2.3", PLAY_API_ROOT: root, RUNNER_TEMP: dir },
      }, (err, stdout, stderr) => (err ? reject(new Error(stderr || err.message)) : resolve(stdout))));
  } finally {
    server.close();
  }

  const app = "/androidpublisher/v3/applications/com.example.app";
  assert.deepEqual(seen.map((s) => `${s.method} ${s.url}`), [
    "POST /token",
    `POST ${app}/edits`,
    `POST /upload${app}/edits/e1/bundles?uploadType=media`,
    `PUT ${app}/edits/e1/tracks/internal`,
    `POST ${app}/edits/e1:commit`,
  ]);

  // The sign-in is a JWT signed with the account's key, for the Play publishing scope only.
  const form = new URLSearchParams(seen[0].body.toString());
  assert.equal(form.get("grant_type"), "urn:ietf:params:oauth:grant-type:jwt-bearer");
  const [h, c, s] = form.get("assertion").split(".");
  const verify = createVerify("RSA-SHA256");
  verify.update(`${h}.${c}`);
  assert.ok(verify.verify(publicKey, Buffer.from(s, "base64url")), "signed with the account's key");
  const claims = JSON.parse(Buffer.from(c, "base64url"));
  assert.equal(claims.iss, "uploader@example.iam.gserviceaccount.com");
  assert.equal(claims.scope, "https://www.googleapis.com/auth/androidpublisher");
  assert.equal(claims.aud, `${root}/token`);
  assert.ok(claims.exp - claims.iat <= 600);

  for (const s of seen.slice(1)) assert.equal(s.auth, "Bearer tok");
  assert.equal(seen[2].body.toString(), "bundle bytes");
  assert.deepEqual(JSON.parse(seen[3].body), {
    track: "internal",
    releases: [{ versionCodes: ["98"], status: "completed", releaseNotes: [{ language: "en-US", text: "RouteMaker v1.2.3" }] }],
  });
});
