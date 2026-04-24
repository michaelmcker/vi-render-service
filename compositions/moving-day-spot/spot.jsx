/* global React, ReactDOM, Stage, Sprite, useTime, useSprite, useTimeline, Easing */

const { useEffect } = React;

// ── Warm-neutral + one accent palette (per user direction) ───────────────────
// Cream paper, charcoal ink, Vertical Impression teal as the one bold accent.
const C = {
  cream:      '#F5EFE4',   // primary background — warm cream
  creamDeep:  '#EBE3D2',   // slightly deeper cream for subtle shifts
  charcoal:   '#1C1A17',   // near-black warm charcoal
  charcoal2:  '#2A2621',
  slate:      '#5A524A',   // muted secondary text
  accent:     '#22C3B2',   // VI teal — the one bold accent
  accentDeep: '#159E90',
  accentSoft: '#BCF3EE',
  navy:       '#0F2B4D',   // only for VI brand logo lockup
};

const FONT = "'Gilroy', system-ui, sans-serif";
const clamp = (v,a,b) => Math.max(a, Math.min(b,v));

// Root label updater
function TimestampLabeler() {
  const { time } = useTimeline();
  useEffect(() => {
    const s = Math.floor(time);
    const root = document.querySelector('[data-spot-root]');
    if (root) root.setAttribute('data-screen-label', `t=${s}s`);
  }, [time]);
  return null;
}

// Eyebrow row — warm charcoal w/ accent rule
function EyebrowRow({ text, color = C.accentDeep, delay = 0 }) {
  const { localTime } = useSprite();
  const t = clamp((localTime - delay) / 0.45, 0, 1);
  const e = Easing.easeOutCubic(t);
  return (
    <div style={{
      fontFamily: FONT, fontWeight: 600, fontSize: 22,
      letterSpacing: '0.2em', textTransform: 'uppercase',
      color, opacity: t, transform: `translateX(${(1-e)*-14}px)`,
      display: 'flex', alignItems: 'center', gap: 16,
    }}>
      <span style={{
        display: 'inline-block', width: 56, height: 2, background: color,
      }} />
      {text}
    </div>
  );
}

// Warm paper background (consistent across scenes)
function PaperBg({ children, variant = 'cream' }) {
  const bg = variant === 'charcoal' ? C.charcoal : C.cream;
  return (
    <div style={{
      position: 'absolute', inset: 0, background: bg, overflow: 'hidden',
    }}>
      {/* Subtle warm vignette */}
      <div style={{
        position: 'absolute', inset: 0,
        background: variant === 'charcoal'
          ? `radial-gradient(ellipse at 30% 40%, rgba(255,240,210,0.04) 0%, transparent 55%)`
          : `radial-gradient(ellipse at 30% 40%, rgba(255,255,255,0.5) 0%, transparent 55%),
             radial-gradient(ellipse at 80% 90%, rgba(28,26,23,0.04) 0%, transparent 55%)`,
      }} />
      {children}
    </div>
  );
}

// Static property-manager eyebrow
function BuildingBadge({ x, y, delay = 0 }) {
  const { localTime } = useSprite();
  const t = clamp((localTime - delay) / 0.4, 0, 1);
  return (
    <div style={{
      position: 'absolute', left: x, top: y,
      opacity: t,
      transform: `translateY(${(1-t)*10}px)`,
      display: 'inline-flex', alignItems: 'center', gap: 12,
      padding: '10px 18px',
      background: 'rgba(28,26,23,0.06)',
      border: `1px solid rgba(28,26,23,0.1)`,
      borderRadius: 999,
      fontFamily: FONT, fontSize: 16, fontWeight: 600,
      letterSpacing: '0.08em', textTransform: 'uppercase',
      color: C.charcoal2,
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: 999, background: C.accent,
      }} />
      Gestionnaires d'immeubles · Property managers
    </div>
  );
}

// ── SCENE 1 (0–3s): Warm hello — type intro ─────────────────────────────────
function SceneOne() {
  const { localTime, duration } = useSprite();
  // FR slides up
  const frT = clamp(localTime / 0.7, 0, 1);
  const frE = Easing.easeOutCubic(frT);
  const enT = clamp((localTime - 0.5) / 0.6, 0, 1);
  const enE = Easing.easeOutCubic(enT);

  const exitStart = duration - 0.5;
  const exit = localTime > exitStart ? clamp((localTime - exitStart) / 0.5, 0, 1) : 0;
  const exitOp = 1 - exit;

  // Slow breathe on scale
  const breathe = 1 + Math.sin(localTime * 1.2) * 0.005;

  return (
    <PaperBg>
      <BuildingBadge x={140} y={120} delay={0.1} />

      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        paddingLeft: 140, paddingRight: 140,
        opacity: exitOp,
        transform: `scale(${breathe})`, transformOrigin: 'center',
      }}>
        {/* FR — large */}
        <div style={{
          fontFamily: FONT, fontWeight: 700, fontSize: 160,
          lineHeight: 0.96, letterSpacing: '-0.04em',
          color: C.charcoal,
          opacity: frT, transform: `translateY(${(1-frE)*22}px)`,
        }}>
          Jour de<br/>
          <span style={{ fontStyle: 'italic', color: C.accentDeep }}>déménagement</span>?
        </div>

        {/* EN — half size */}
        <div style={{
          fontFamily: FONT, fontWeight: 500, fontSize: 72,
          lineHeight: 1.0, letterSpacing: '-0.02em',
          color: C.slate, marginTop: 36,
          opacity: enT, transform: `translateY(${(1-enE)*14}px)`,
        }}>
          Moving <span style={{ fontStyle: 'italic' }}>day</span>?
        </div>
      </div>
    </PaperBg>
  );
}

// ── SCENE 2 (3–7s): The offer — GRATUIT / FREE ──────────────────────────────
function SceneTwo() {
  const { localTime, duration } = useSprite();
  const eyeT = clamp(localTime / 0.4, 0, 1);
  const frT = clamp((localTime - 0.25) / 0.6, 0, 1);
  const frE = Easing.easeOutCubic(frT);
  const enT = clamp((localTime - 0.6) / 0.55, 0, 1);
  const enE = Easing.easeOutCubic(enT);
  // GRATUIT pill stamp
  const stampT = clamp((localTime - 1.0) / 0.45, 0, 1);
  const stampE = Easing.easeOutBack(stampT);
  // Subtitle "Extra revenue for your building"
  const revT = clamp((localTime - 1.8) / 0.55, 0, 1);
  const revE = Easing.easeOutCubic(revT);

  const exitStart = duration - 0.5;
  const exit = localTime > exitStart ? clamp((localTime - exitStart) / 0.5, 0, 1) : 0;
  const exitOp = 1 - exit;

  return (
    <PaperBg>
      <div style={{
        position: 'absolute', inset: 0,
        paddingLeft: 140, paddingRight: 140,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        opacity: exitOp,
      }}>
        <div style={{ opacity: eyeT, marginBottom: 40 }}>
          <EyebrowRow text="L'offre · The offer" color={C.accentDeep} />
        </div>

        {/* FR — massive, 2 lines */}
        <div style={{
          fontFamily: FONT, fontWeight: 800, fontSize: 148,
          lineHeight: 0.92, letterSpacing: '-0.042em',
          color: C.charcoal,
          opacity: frT, transform: `translateY(${(1-frE)*24}px)`,
        }}>
          Couvre-élévateurs
        </div>
        <div style={{
          display: 'flex', alignItems: 'baseline', gap: 32, flexWrap: 'wrap',
          marginTop: 6,
          opacity: frT, transform: `translateY(${(1-frE)*24}px)`,
        }}>
          <span style={{
            fontFamily: FONT, fontWeight: 800, fontSize: 148,
            lineHeight: 0.92, letterSpacing: '-0.042em',
            color: C.charcoal, fontStyle: 'italic',
          }}>gratuits.</span>

          {/* GRATUIT stamp */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 12,
            padding: '14px 30px',
            background: C.accent,
            color: C.charcoal,
            borderRadius: 999,
            fontFamily: FONT, fontWeight: 800, fontSize: 44,
            letterSpacing: '0.04em', textTransform: 'uppercase',
            transform: `scale(${stampE}) rotate(${-5 * stampE}deg)`,
            opacity: stampT,
            boxShadow: '0 10px 30px rgba(34,195,178,0.28)',
          }}>0 $</div>
        </div>

        {/* EN — half size */}
        <div style={{
          fontFamily: FONT, fontWeight: 500, fontSize: 66,
          lineHeight: 1.02, letterSpacing: '-0.02em',
          color: C.slate, marginTop: 38,
          opacity: enT, transform: `translateY(${(1-enE)*14}px)`,
        }}>
          Free elevator pads for <span style={{ fontStyle: 'italic' }}>moving day</span>.
        </div>

        {/* Revenue line */}
        <div style={{
          marginTop: 52,
          paddingTop: 30,
          borderTop: `1px solid rgba(28,26,23,0.12)`,
          maxWidth: 1300,
          opacity: revT, transform: `translateY(${(1-revE)*12}px)`,
        }}>
          <div style={{
            fontFamily: FONT, fontWeight: 700, fontSize: 38,
            lineHeight: 1.1, letterSpacing: '-0.015em',
            color: C.charcoal,
          }}>
            Avec un <span style={{ fontStyle: 'italic', color: C.accentDeep }}>revenu supplémentaire</span> pour votre immeuble.
          </div>
          <div style={{
            fontFamily: FONT, fontWeight: 400, fontSize: 20,
            color: C.slate, marginTop: 6,
          }}>
            Plus a little extra revenue for your building.
          </div>
        </div>
      </div>
    </PaperBg>
  );
}

// ── SCENE 3 (7–15s): Held CTA — Call Lauren, April 30 ───────────────────────
function SceneCTA() {
  const { localTime, duration } = useSprite();
  // Quick build-in (~1.2s), then hold for ~6.8s
  const eyeT = clamp(localTime / 0.4, 0, 1);
  const frT = clamp((localTime - 0.2) / 0.65, 0, 1);
  const frE = Easing.easeOutCubic(frT);
  const enT = clamp((localTime - 0.55) / 0.55, 0, 1);
  const enE = Easing.easeOutCubic(enT);
  const contactT = clamp((localTime - 1.1) / 0.7, 0, 1);
  const contactE = Easing.easeOutCubic(contactT);
  const logoT = clamp((localTime - 1.9) / 0.55, 0, 1);

  // Subtle breathe across the hold, gentle pulse on accent dot
  const breathe = 1 + Math.sin(localTime * 0.8) * 0.003;
  const pulse = 1 + Math.sin(localTime * 2.4) * 0.18;

  return (
    <PaperBg>
      <div style={{
        position: 'absolute', inset: 0,
        paddingLeft: 140, paddingRight: 140, paddingTop: 110, paddingBottom: 100,
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
        transform: `scale(${breathe})`, transformOrigin: 'center',
      }}>
        {/* Top: eyebrow + headline */}
        <div>
          <div style={{ opacity: eyeT, marginBottom: 40, display: 'flex', alignItems: 'center', gap: 24 }}>
            <EyebrowRow text="D'ici le 30 avril · By April 30" color={C.accentDeep} />
            <div style={{
              width: 14, height: 14, borderRadius: 999,
              background: C.accent,
              boxShadow: `0 0 0 ${6 * pulse}px rgba(34,195,178,0.2)`,
              opacity: eyeT,
            }} />
          </div>

          {/* FR headline — massive */}
          <div style={{
            fontFamily: FONT, fontWeight: 700, fontSize: 172,
            lineHeight: 0.94, letterSpacing: '-0.042em',
            color: C.charcoal,
            opacity: frT, transform: `translateY(${(1-frE)*26}px)`,
          }}>
            Appelez <span style={{ fontStyle: 'italic', color: C.accentDeep }}>Lauren</span>.
          </div>
          {/* EN ~half */}
          <div style={{
            fontFamily: FONT, fontWeight: 500, fontSize: 76,
            lineHeight: 1.0, letterSpacing: '-0.022em',
            color: C.slate, marginTop: 30,
            opacity: enT, transform: `translateY(${(1-enE)*14}px)`,
          }}>
            <span style={{ fontStyle: 'italic' }}>Call Lauren</span> to claim yours.
          </div>
        </div>

        {/* Middle: single quiet contact row */}
        <div style={{
          opacity: contactT, transform: `translateY(${(1-contactE)*16}px)`,
          display: 'flex', alignItems: 'center', gap: 64, flexWrap: 'wrap',
          paddingTop: 36, paddingBottom: 36,
          borderTop: `1px solid rgba(28,26,23,0.14)`,
          borderBottom: `1px solid rgba(28,26,23,0.14)`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{
              width: 52, height: 52, borderRadius: 999, background: C.charcoal,
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"
                  stroke={C.accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div style={{
              fontFamily: FONT, fontWeight: 700, fontSize: 52,
              color: C.charcoal, letterSpacing: '-0.02em', lineHeight: 1,
            }}>289-685-7977</div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{
              width: 52, height: 52, borderRadius: 999, background: C.charcoal,
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <rect x="2.5" y="4.5" width="19" height="15" rx="2" stroke={C.accent} strokeWidth="2"/>
                <path d="M3 6l9 7 9-7" stroke={C.accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div style={{
              fontFamily: FONT, fontWeight: 700, fontSize: 40,
              color: C.charcoal, letterSpacing: '-0.015em', lineHeight: 1,
            }}>llazar@verticalcity.com</div>
          </div>
        </div>

        {/* Bottom: tagline + VI logo */}
        <div style={{
          opacity: logoT,
          display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
        }}>
          <div style={{
            fontFamily: FONT, fontWeight: 500, fontSize: 20,
            letterSpacing: '0.18em', textTransform: 'uppercase',
            color: C.slate,
          }}>
            Couvre-élévateurs gratuits · Free elevator pads
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
            <img src="assets/VI_Logo_140px.png" alt="Vertical Impression"
                 style={{ height: 58, display: 'block' }} />
            <div style={{
              fontFamily: FONT, fontSize: 12, fontWeight: 500,
              letterSpacing: '0.22em', textTransform: 'uppercase',
              color: C.slate,
            }}>A Vertical City brand</div>
          </div>
        </div>
      </div>
    </PaperBg>
  );
}

// ── (unused — retained to avoid breaking anything) ──────────────────────────
function SceneThree_UNUSED() {
  const { localTime, duration } = useSprite();
  const eyeT = clamp(localTime / 0.4, 0, 1);
  const frT = clamp((localTime - 0.2) / 0.6, 0, 1);
  const frE = Easing.easeOutCubic(frT);
  const enT = clamp((localTime - 0.55) / 0.55, 0, 1);
  const enE = Easing.easeOutCubic(enT);
  const cardT = clamp((localTime - 1.1) / 0.6, 0, 1);
  const cardE = Easing.easeOutCubic(cardT);
  const card2T = clamp((localTime - 1.45) / 0.6, 0, 1);
  const card2E = Easing.easeOutCubic(card2T);

  const exitStart = duration - 0.5;
  const exit = localTime > exitStart ? clamp((localTime - exitStart) / 0.5, 0, 1) : 0;
  const exitOp = 1 - exit;

  return (
    <PaperBg>
      <div style={{
        position: 'absolute', inset: 0,
        paddingLeft: 140, paddingRight: 140, paddingTop: 110, paddingBottom: 110,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        opacity: exitOp,
      }}>
        <div style={{ opacity: eyeT, marginBottom: 36 }}>
          <EyebrowRow text="Contactez-nous · Get in touch" color={C.accentDeep} />
        </div>

        {/* FR heading */}
        <div style={{
          fontFamily: FONT, fontWeight: 700, fontSize: 130,
          lineHeight: 0.96, letterSpacing: '-0.038em',
          color: C.charcoal,
          opacity: frT, transform: `translateY(${(1-frE)*22}px)`,
        }}>
          Appelez <span style={{ fontStyle: 'italic', color: C.accentDeep }}>Lauren</span>.
        </div>
        {/* EN half size */}
        <div style={{
          fontFamily: FONT, fontWeight: 500, fontSize: 58,
          lineHeight: 1.0, letterSpacing: '-0.02em',
          color: C.slate, marginTop: 20,
          opacity: enT, transform: `translateY(${(1-enE)*14}px)`,
        }}>
          <span style={{ fontStyle: 'italic' }}>Call Lauren</span> to claim yours.
        </div>

        {/* Contact cards */}
        <div style={{
          marginTop: 56,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28,
        }}>
          {/* Phone */}
          <div style={{
            opacity: cardT, transform: `translateY(${(1-cardE)*18}px)`,
            background: C.charcoal,
            borderRadius: 22,
            padding: '34px 40px',
            display: 'flex', alignItems: 'center', gap: 26,
            boxShadow: '0 14px 36px rgba(28,26,23,0.16)',
          }}>
            <div style={{
              width: 64, height: 64, borderRadius: 999,
              background: C.accent,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"
                  stroke={C.charcoal} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div>
              <div style={{
                fontFamily: FONT, fontSize: 14, fontWeight: 600,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: C.accentSoft, marginBottom: 6,
              }}>Téléphone · Phone</div>
              <div style={{
                fontFamily: FONT, fontSize: 48, fontWeight: 700,
                color: C.cream, letterSpacing: '-0.02em', lineHeight: 1,
              }}>289-685-7977</div>
            </div>
          </div>

          {/* Email */}
          <div style={{
            opacity: card2T, transform: `translateY(${(1-card2E)*18}px)`,
            background: C.cream,
            border: `2px solid ${C.charcoal}`,
            borderRadius: 22,
            padding: '34px 40px',
            display: 'flex', alignItems: 'center', gap: 26,
          }}>
            <div style={{
              width: 64, height: 64, borderRadius: 999,
              background: C.charcoal,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                <rect x="2.5" y="4.5" width="19" height="15" rx="2" stroke={C.accent} strokeWidth="2"/>
                <path d="M3 6l9 7 9-7" stroke={C.accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontFamily: FONT, fontSize: 14, fontWeight: 600,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: C.accentDeep, marginBottom: 6,
              }}>Courriel · Email</div>
              <div style={{
                fontFamily: FONT, fontSize: 34, fontWeight: 700,
                color: C.charcoal, letterSpacing: '-0.015em', lineHeight: 1,
                whiteSpace: 'nowrap',
              }}>llazar@verticalcity.com</div>
            </div>
          </div>
        </div>
      </div>
    </PaperBg>
  );
}

// ── SCENE 4 (UNUSED) ────────────────────────────────────────────────────────
function SceneFour_UNUSED() {
  const { localTime, duration } = useSprite();
  const eyeT = clamp(localTime / 0.4, 0, 1);
  const frT = clamp((localTime - 0.25) / 0.65, 0, 1);
  const frE = Easing.easeOutCubic(frT);
  const enT = clamp((localTime - 0.65) / 0.55, 0, 1);
  const enE = Easing.easeOutCubic(enT);
  const dotT = clamp((localTime - 1.0) / 0.4, 0, 1);
  const dotE = Easing.easeOutBack(dotT);
  const logoT = clamp((localTime - 1.6) / 0.6, 0, 1);
  const logoE = Easing.easeOutCubic(logoT);

  // soft pulse on the deadline dot
  const pulse = 1 + Math.sin(localTime * 3) * 0.12;

  return (
    <PaperBg>
      <div style={{
        position: 'absolute', inset: 0,
        paddingLeft: 140, paddingRight: 140, paddingTop: 110, paddingBottom: 110,
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      }}>
        {/* Top block: deadline */}
        <div>
          <div style={{ opacity: eyeT, marginBottom: 44 }}>
            <EyebrowRow text="Date limite · Deadline" color={C.accentDeep} />
          </div>

          {/* Deadline dot + FR */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 36 }}>
            <div style={{
              marginTop: 38,
              opacity: dotT, transform: `scale(${dotE})`,
              width: 28, height: 28, borderRadius: 999,
              background: C.accent,
              boxShadow: `0 0 0 ${12 * pulse}px rgba(34,195,178,0.18)`,
              flexShrink: 0,
            }} />
            <div>
              <div style={{
                fontFamily: FONT, fontWeight: 700, fontSize: 168,
                lineHeight: 0.94, letterSpacing: '-0.042em',
                color: C.charcoal,
                opacity: frT, transform: `translateY(${(1-frE)*24}px)`,
              }}>
                D'ici le<br/>
                <span style={{ fontStyle: 'italic', color: C.accentDeep }}>30 avril</span>.
              </div>
              <div style={{
                fontFamily: FONT, fontWeight: 500, fontSize: 74,
                lineHeight: 1.0, letterSpacing: '-0.022em',
                color: C.slate, marginTop: 28,
                opacity: enT, transform: `translateY(${(1-enE)*14}px)`,
              }}>
                By <span style={{ fontStyle: 'italic' }}>April 30</span>.
              </div>
            </div>
          </div>
        </div>

        {/* Bottom row: logo + contact recap */}
        <div style={{
          opacity: logoT, transform: `translateY(${(1-logoE)*12}px)`,
          display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
          paddingTop: 30,
          borderTop: `1px solid rgba(28,26,23,0.14)`,
        }}>
          <div>
            <div style={{
              fontFamily: FONT, fontSize: 13, fontWeight: 600,
              letterSpacing: '0.2em', textTransform: 'uppercase',
              color: C.slate, marginBottom: 10,
            }}>Appelez · Call</div>
            <div style={{
              fontFamily: FONT, fontWeight: 700, fontSize: 44,
              color: C.charcoal, letterSpacing: '-0.02em', lineHeight: 1,
            }}>Lauren · 289-685-7977</div>
            <div style={{
              fontFamily: FONT, fontWeight: 500, fontSize: 22,
              color: C.slate, marginTop: 10, letterSpacing: '-0.01em',
            }}>llazar@verticalcity.com</div>
          </div>

          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8,
          }}>
            <img src="assets/VI_Logo_140px.png" alt="Vertical Impression"
                 style={{ height: 58, display: 'block' }} />
            <div style={{
              fontFamily: FONT, fontSize: 12, fontWeight: 500,
              letterSpacing: '0.22em', textTransform: 'uppercase',
              color: C.slate,
            }}>A Vertical City brand</div>
          </div>
        </div>
      </div>
    </PaperBg>
  );
}

// ── Main spot ────────────────────────────────────────────────────────────────
function Spot() {
  return (
    <div data-spot-root="true" data-screen-label="t=0s" style={{ width: '100%', height: '100%' }}>
      <Stage
        width={1920}
        height={1080}
        duration={15}
        background="#000000"
        persistKey="moving-day-spot"
        loop={true}
        autoplay={true}
      >
        <TimestampLabeler />

        <Sprite start={0} end={3}><SceneOne /></Sprite>
        <Sprite start={3} end={7}><SceneTwo /></Sprite>
        <Sprite start={7} end={15}><SceneCTA /></Sprite>
      </Stage>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<Spot />);
