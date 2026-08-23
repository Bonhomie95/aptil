import type { Metadata } from "next";
import { LegalShell, Section } from "@/components/legal-shell";

export const metadata: Metadata = {
  title: "Privacy Policy — Aptil",
  description: "What personal data Aptil holds, why, and how to get it back or delete it.",
};

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" updated="20 August 2026">
      <p>
        This explains what personal data Aptil holds and what you can do about it. It is
        a template that must be reviewed by a qualified lawyer before commercial use.
      </p>

      <Section heading="What we collect">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>
            <b className="text-foreground">Account data</b> — email address, name, and a
            hash of your password (never the password itself).
          </li>
          <li>
            <b className="text-foreground">Profile and CV data</b> — the résumé you
            upload and the structured details extracted from it: contact details, work
            history, education, certifications, and skills.
          </li>
          <li>
            <b className="text-foreground">Application activity</b> — which roles you
            were matched to, what was submitted, and the status of each application.
          </li>
          <li>
            <b className="text-foreground">Interview practice</b> — your answers and the
            feedback generated for them.
          </li>
          <li>
            <b className="text-foreground">Site credentials</b> — where you ask us to
            store a login for a job site, encrypted at rest with a unique password per
            site.
          </li>
        </ul>
      </Section>

      <Section heading="Why we hold it">
        <p>
          To provide the service you asked for: matching you to roles, completing
          application forms on your instruction, and generating practice interviews. We
          do not sell your data or use it for advertising.
        </p>
      </Section>

      <Section heading="Who we share it with">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>
            <b className="text-foreground">Employers</b> — the profile and résumé data
            needed to complete an application you authorised.
          </li>
          <li>
            <b className="text-foreground">AI providers</b> — CV text and job
            descriptions are sent to the model provider configured for this deployment
            in order to parse, tailor, and score. Self-hosted deployments can route this
            to a local model instead.
          </li>
          <li>
            <b className="text-foreground">Payment processor</b> — Stripe handles card
            details. We never see or store your card number.
          </li>
        </ul>
      </Section>

      <Section heading="Security">
        <p>
          Passwords are hashed with Argon2id. Site credentials are encrypted at rest.
          Access tokens are short-lived, refresh tokens rotate on use, and changing your
          password invalidates every existing session.
        </p>
      </Section>

      <Section heading="Your rights">
        <p>
          You can download everything we hold about you as JSON, and permanently delete
          your account and all associated data, from{" "}
          <b className="text-foreground">Settings</b> at any time. Deletion removes your
          profile, résumés, stored credentials, applications and interview history from
          our database and object storage.
        </p>
      </Section>

      <Section heading="Retention">
        <p>
          We keep your data while your account is open. Deleting your account removes it
          immediately; backups roll off within 30 days.
        </p>
      </Section>

      <Section heading="Contact">
        <p>Privacy questions or requests: privacy@aptil.ai</p>
      </Section>
    </LegalShell>
  );
}
