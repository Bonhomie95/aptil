"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/**
 * Scroll-reveal wrapper.
 *
 * The entrance animation is an *enhancement*, never a precondition for seeing
 * the content. The naive version rendered `opacity: 0` into the server HTML and
 * relied entirely on an IntersectionObserver firing — so if JS failed, was
 * blocked, or the observer never fired (a background tab, an unusual viewport),
 * the whole section stayed invisible with no way to recover.
 *
 * Safeguards here:
 *  - `prefers-reduced-motion` skips the animation entirely.
 *  - A mount-time fallback reveals the content regardless after a short grace
 *    period, so a missed observer degrades to "no animation", not "no content".
 */
const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const item: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
  },
};

// If the observer hasn't revealed the section by now, show it anyway.
const FALLBACK_MS = 1200;

export function Reveal({
  children,
  className,
  as = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "section";
}) {
  const reduceMotion = useReducedMotion();
  const [forceShow, setForceShow] = useState(false);
  const revealed = useRef(false);

  useEffect(() => {
    const id = setTimeout(() => {
      if (!revealed.current) setForceShow(true);
    }, FALLBACK_MS);
    return () => clearTimeout(id);
  }, []);

  const Comp = as === "section" ? motion.section : motion.div;

  // No animation at all when the user asked for reduced motion.
  if (reduceMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <Comp
      className={className}
      variants={container}
      initial="hidden"
      animate={forceShow ? "show" : undefined}
      whileInView="show"
      onViewportEnter={() => {
        revealed.current = true;
      }}
      viewport={{ once: true, margin: "-80px" }}
    >
      {children}
    </Comp>
  );
}

export function RevealItem({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const reduceMotion = useReducedMotion();
  if (reduceMotion) {
    return <div className={className}>{children}</div>;
  }
  return (
    <motion.div variants={item} className={className}>
      {children}
    </motion.div>
  );
}
