import { Navbar } from "@/components/navbar";
import { Hero } from "@/components/hero";
import { Sources } from "@/components/sections/sources";
import { Features } from "@/components/sections/features";
import { HowItWorks } from "@/components/sections/how-it-works";
import { Pricing } from "@/components/sections/pricing";
import { FAQ } from "@/components/sections/faq";
import { CTA } from "@/components/sections/cta";
import { SiteFooter } from "@/components/site-footer";

export default function Home() {
  return (
    <>
      <Navbar />
      <main id="main" className="min-h-screen overflow-x-clip">
        <Hero />
        <Sources />
        <Features />
        <HowItWorks />
        <Pricing />
        <FAQ />
        <CTA />
      </main>
      <SiteFooter marketing />
    </>
  );
}
