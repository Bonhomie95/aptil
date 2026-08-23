import type { Metadata } from "next";
import { LegalShell, Section } from "@/components/legal-shell";

export const metadata: Metadata = {
  title: "Terms of Service — Aptil",
  description: "The terms that govern your use of Aptil.",
};

export default function TermsPage() {
  return (
    <LegalShell title="Terms of Service" updated="20 August 2026">
      <p>
        These terms govern your use of Aptil. This is a template that must be reviewed
        by a qualified lawyer before you rely on it commercially.
      </p>

      <Section heading="1. What Aptil does">
        <p>
          Aptil discovers job postings from official job APIs and public ATS boards,
          helps you tailor your résumé, submits applications through those official
          channels on your instruction, and runs practice interviews.
        </p>
      </Section>

      <Section heading="2. Your account">
        <p>
          You must give accurate information and keep your credentials secure. You are
          responsible for activity on your account. You must be old enough to enter a
          contract in your jurisdiction.
        </p>
      </Section>

      <Section heading="3. Applications submitted on your behalf">
        <p>
          When you enable automated applications you authorise us to submit the profile
          and résumé data you have provided to employers through their own application
          forms. We do not log into third-party accounts on your behalf, do not
          impersonate you beyond completing those forms, and never bypass CAPTCHAs or
          bot-detection. If a site presents a challenge, we stop and hand the
          application back to you.
        </p>
        <p>
          You remain responsible for the accuracy of what you tell us. We do not
          guarantee interviews, offers, or employment outcomes.
        </p>
      </Section>

      <Section heading="4. AI-generated content">
        <p>
          Résumé tailoring and interview feedback are produced by large language models
          and can contain mistakes. Review anything generated before relying on it. We
          instruct our models never to invent employers, titles, dates, or credentials,
          but you should still check.
        </p>
      </Section>

      <Section heading="5. Acceptable use">
        <p>
          Do not use Aptil to submit false information to employers, to apply on behalf
          of another person without their consent, to scrape or resell our data, or to
          attempt to disrupt the service.
        </p>
      </Section>

      <Section heading="6. Plans and billing">
        <p>
          Paid plans renew monthly until cancelled. Usage allowances reset each billing
          period. You can cancel at any time from the billing portal; access continues
          until the end of the paid period.
        </p>
      </Section>

      <Section heading="7. Termination">
        <p>
          You may delete your account at any time from Settings, which permanently
          removes your data. We may suspend accounts that breach these terms.
        </p>
      </Section>

      <Section heading="8. Liability">
        <p>
          The service is provided &ldquo;as is&rdquo;. To the maximum extent permitted by
          law we exclude implied warranties and limit our liability to the amount you
          paid us in the preceding twelve months.
        </p>
      </Section>

      <Section heading="9. Contact">
        <p>Questions about these terms: legal@aptil.ai</p>
      </Section>
    </LegalShell>
  );
}
