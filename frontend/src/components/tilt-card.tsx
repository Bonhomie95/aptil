"use client";

import { useRef } from "react";
import { motion, useMotionValue, useSpring, useReducedMotion } from "framer-motion";

// Max rotation in degrees. Small enough to read as "a surface with weight",
// large enough that it's visible — anything past ~10deg starts to feel gimmicky.
const TILT_DEG = 9;

/**
 * Pointer-tracked tilt + lift for landing-page cards. `shadow-card` gives the
 * card a resting elevation — visible without a hover, so it reads as an
 * object sitting above the page rather than a bordered rectangle — and
 * `shadow-float` deepens that on hover, alongside the tilt and lift.
 *
 * The shadow classes are plain CSS `:hover` rules (not a framer animation),
 * so they still apply under prefers-reduced-motion — only the transform-based
 * tilt/lift is skipped, per the global reduced-motion rule in globals.css.
 */
export function TiltCard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const rotateX = useSpring(rawX, { stiffness: 300, damping: 30 });
  const rotateY = useSpring(rawY, { stiffness: 300, damping: 30 });

  const shadowClass =
    "shadow-card transition-shadow duration-200 ease-ease hover:shadow-float";

  if (reduceMotion) {
    return <div className={`${shadowClass} ${className}`}>{children}</div>;
  }

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    rawY.set(px * TILT_DEG);
    rawX.set(py * -TILT_DEG);
  }

  function handleMouseLeave() {
    rawX.set(0);
    rawY.set(0);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      whileHover={{ y: -6 }}
      style={{ rotateX, rotateY, transformPerspective: 800 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      className={`${shadowClass} ${className}`}
    >
      {children}
    </motion.div>
  );
}
