# Design System of Aimprove

## 1. Visual Theme & Atmosphere

Aimprove's website is a masterclass in playful authority — a design system that refuses to choose between friendly and credible, instead insisting on both simultaneously. The homepage opens on a canvas of blazing gold (`#FFD747`) with deep navy text (`#14093B`), a combination that reads as warm, energetic, and supremely confident. This is not corporate softness, nor is it startup chaos: it is a carefully orchestrated joyfulness, where every color feels chosen by someone who genuinely loves what they teach.

The dominant visual motif is organic shapes in motion: wave dividers that separate sections like rolling hills, an animated pink ribbon that winds through the homepage, floating geometric squares spinning at idle angles, and green blob shapes that crowd the corners of hero sections like applauding hands. The cat mascot — always rendered as a clean white line-art face on a colored background — appears on every inner page, each time against a different brand color (blue for courses, green for blog, yellow for home), creating a system where personality is the constant and color is the variable.

The typography is entirely Rubik, a rounded, humanist Hebrew-Latin font that reinforces the approachable-expert positioning. At display sizes (74px, weight 800), it feels powerful and declarative. In body text (16px, line-height 2.0), it breathes spaciously. Rubik's slightly rounded terminals soften what would otherwise be aggressive weight, making even bold headlines feel inviting rather than demanding.

The color palette is deliberately broad and unapologetically saturated: yellow, green, blue, pink, purple, navy — all appear within a single scroll. Yet the system holds together because each color occupies its own section or component, never competing directly. The dark navy (`#14093B`) serves as the unifying constant — primary text, dark sections, main CTAs — anchoring the spectacle.

**Key Characteristics:**
- Gold-on-navy hero (`#FFD747` on `#14093B`) as the brand's defining moment — warm, bold, Israeli
- Rubik exclusively across all text — the rounded humanist font that feels like a knowledgeable friend
- Pill buttons (border-radius 50px–88px) — the most pill-shaped in any brand system; roundness is a brand value
- Cat mascot in white SVG that changes background color per page type (hero color = page identity)
- Organic wave dividers between every section — no hard horizontal cuts, only flowing transitions
- Floating rotated squares as decoration — blue, green, pink, wine — scattered throughout like confetti
- Pink animated ribbon connecting sections on the homepage
- Green leaf decorations at hero corners — natural, organic, warm
- RTL Hebrew-first layout with full LTR compatibility

## 2. Color Palette & Roles

### Hero & Primary Brand
- **Gold Yellow** (`#FFD747`): The hero background of the main homepage, CTA secondary buttons ("לאימפרוב פלוס", "לקריאה"), and the checkout hover color. The single most iconic Aimprove color — warm, energetic, unmistakably the brand.
- **Dark Navy** (`#14093B`): Primary text color, dark section backgrounds (footer, Aimprove Plus section), and the most important CTA buttons. The anchor of the palette — everything else is defined against it.
- **Mid Navy** (`#1F1341`): Navigation pill button background, some primary CTAs. Slightly lighter than Dark Navy, used when full depth would be overpowering.

### Page-Type Hero Colors
- **Course Blue** (`#2473C8`): Hero background for the AI course page. Confident, educational, institutional without being cold.
- **Blog Green** (`#05905D`): Hero background for the blog page. Organic, fresh, editorial.

### Accent & Energy
- **Bright Green** (`#6BD22B`): Organic blob shape in homepage hero, footer/contact section background. Maximum energy green — life, growth, optimism.
- **Pink/Magenta** (`#FF6DB3`): The "האווירה" (vibe) section background, the animated decorative ribbon on homepage. Playful, social, community-feeling.
- **Purple** (`#6762FF`): Statistics and counter boxes. Premium, trustworthy, numerical authority.
- **Lime** (`#CFFF0B`): Decorative accent, occasional highlights. Maximum brightness, use sparingly.

### Course Card Colors (Curriculum Palette)
- **Wine/Bordeaux** (`#A52756`): Course lesson card background — warm-dark, premium.
- **Teal Green** (`#05905D`): Course lesson card background — fresh, educational.
- **Deep Purple** (`#6762FF`): Course lesson card background — knowledge, depth.
- **Pink** (`#FE6DB2`): Course lesson card background — approachable, welcoming.

### Neutral & Surface
- **White** (`#FFFFFF`): Body section backgrounds, card surfaces, button text on dark backgrounds.
- **Light Mint** (`#E0F5ED`): Organizations/B2B section background — calm, trustworthy, corporate-adjacent.
- **Light Blue** (`#F1F8FF`): Blog cards background — clean, readable, airy.
- **Light Gray-Blue** (`#F0F3F8`): Subtle surface tinting for form areas and light sections.

### Text
- **Primary Text Dark** (`#14093B`): All headings, dark text. Not pure black — the warm dark navy prevents starkness.
- **Body Text** (`#333333`): Standard paragraph text. Dark gray that pairs with any background.
- **Muted** (`#706A70`): Secondary, placeholder, and de-emphasized text.

### Interactive Blue
- **Link Blue** (`#2473C8`): Links and interactive elements that aren't primary CTAs.

## 3. Typography Rules

### Font Family
- **Primary**: `Rubik`, with fallbacks: `Arial, system-ui, Tahoma, sans-serif`
- **Hebrew Support**: Rubik provides full RTL Hebrew character support natively
- **No monospace system**: Code and technical content uses default system monospace; Aimprove is a non-technical educator brand

### Hierarchy

| Role | Size | Weight | Line Height | Letter Spacing | Color | Notes |
|------|------|--------|-------------|----------------|-------|-------|
| Display Hero | 74px | 800 | 1.0 (74px) | normal | `#14093B` | Homepage H1, maximum impact |
| Section Hero | 48–56px | 800 | 1.1 | normal | `#14093B` | Inner page H1 titles |
| Blog Card Title | 24px | 800 | 1.3 | normal | `#14093B` | Cards, post headings |
| Section Heading | 20px | 700 | 1.3 | normal | `#14093B` | Feature section H3 |
| Subtitle / Lead | 22px | 400 | 1.4 | normal | `#14093B` | Hero subtitle (H2) |
| Body Large | 18px | 400 | 1.7 | normal | `#333333` | Feature descriptions |
| Body | 16px | 400–700 | 2.0 (32px) | normal | `#333333` | Standard reading text |
| Button | 22px | 700 | 1.0 | normal | varies | Primary CTA text |
| Button Small | 16px | 700 | 1.0 | normal | varies | Secondary button text |
| Nav | 21px | 700 | 1.0 | normal | `#FFFFFF` | Navigation pill button |
| Caption / Label | 14px | 400 | 1.5 | normal | `#706A70` | Metadata, form labels |

### Principles
- **Rubik is the entire system**: There is no secondary font, no monospace exception, no display variant. Rubik's weight range (300–900) and its warm rounded letterforms do all the work.
- **Weight as contrast**: The gap between 400 (body) and 800 (hero) is extreme — this is intentional. The visual rhythm swings dramatically between quiet reading and bold declaration.
- **Line-height 2.0 for body**: At 16px, body text uses 32px line-height. This is generous — it prioritizes readability and spaciousness over density.
- **RTL first**: All layouts are designed right-to-left. Text aligns right, flex direction reverses, padding-inline values reflect Hebrew reading direction.
- **No letter-spacing manipulation**: Unlike Linear or Stripe, Aimprove uses `letter-spacing: normal` throughout. Rubik's default spacing is trusted as correct.

## 4. Component Stylings

### Buttons

**Primary Dark (Main CTA)**
- Background: `#1F1341`
- Text: `#FFFFFF`
- Padding: `12px 28px`
- Border-radius: `50px`
- Font: 22px Rubik weight 700
- Hover: background shifts to `#14093B`
- Use: "לקורס לומדים AI", "לאימפרוב לארגונים", "שריינו מקום"

**Primary Yellow (Secondary CTA)**
- Background: `#FFD747`
- Text: `#14093B`
- Padding: `12px 28px`
- Border-radius: `50px`
- Font: 22px Rubik weight 700
- Hover: background brightens slightly
- Use: "לאימפרוב פלוס", "לקריאה" on blog cards, checkout highlights

**Outlined / Ghost**
- Background: transparent
- Text: `#1F1341`
- Border: `1px solid #1F1341`
- Padding: `12px 28px`
- Border-radius: `50px`
- Font: 22px Rubik weight 700
- Use: "לחברות וארגונים" (secondary action alongside primary)

**Navigation Pill**
- Background: `#1F1341`
- Text: `#FFFFFF`
- Padding: `10px 24px`
- Border-radius: `88px`
- Font: 21px Rubik weight 700
- Use: "צור קשר" in top navigation bar

**WhatsApp Floating Button**
- Background: `#25D366` (WhatsApp green)
- Border-radius: `100%`
- Fixed position bottom-left
- Persistent across all pages

### Cards & Containers

**Course Lesson Card**
- Background: one of the curriculum colors (`#A52756`, `#05905D`, `#6762FF`, `#FE6DB2`, `#2473C8`, `#FFD747`)
- Text: `#FFFFFF` (or `#14093B` on yellow)
- Border-radius: `15px`
- Padding: `30px 25px`
- No border
- No shadow
- Use: Lesson overview cards in course curriculum sections

**Feature / Organization Card**
- Background: `#E0F5ED` (light mint)
- Border-radius: `15px 15px 0px 0px` (top-rounded only) or `15px`
- Padding: `40px`
- Shadow: `rgba(0, 0, 0, 0.1) 0px 0px 10px 0px`
- Use: B2B / organization feature sections

**Blog Post Card**
- Background: `#F1F8FF`
- Border-radius: `10px`
- Padding: `20px`
- Shadow: `rgba(59, 115, 194, 0.15) 0px 0px 10px 0px`
- Title: 24px weight 800, `#14093B`
- Use: Blog listing page cards

**Quote / Testimonial Banner**
- Background: `#1F1341`
- Text: `#FFFFFF`
- Border-radius: `15px`
- Padding: `40px 30px`
- Font: 24–30px weight 700
- Use: Highlighted student quotes, social proof moments

**Statistics Box**
- Background: `#6762FF`
- Text: `#FFFFFF`
- Border-radius: `15px`
- Font: 48–60px weight 800 (the number), 16px weight 400 (the label)
- Use: "3,784 אנשים" counter boxes

### Navigation

- Sticky header with dark navy pill button ("צור קשר") right-aligned
- Hamburger menu (`☰`) as secondary nav toggle on left
- User account icon center-right
- Background: transparent over hero, solid `#FFFFFF` on scroll
- No underlines, no hover effects on nav links
- Mobile: hamburger toggle only, no visible link list

### Decorative Elements

**Wave Divider**
- SVG organic wave shape at bottom of colored sections
- Transitions seamlessly into the next section's background color
- Used between every major section transition

**Floating Geometric Shapes**
- Rotated squares (45°) in `#2473C8` (blue), `#6BD22B` (green), `#FF6DB3` (pink), `#A52756` (wine)
- Scattered across section transitions and feature areas
- Sizes: approximately 40px–80px
- No shadow, no border — flat colored fills

**Cat Mascot**
- White SVG line-art face
- Always on a solid colored background matching the page hero
- Appears at approximately 200px–280px width
- Positioned right-of-center in hero sections

**Green Leaves**
- Decorative SVG leaf clusters
- Appear at top corners of yellow hero sections
- Color: `#6BD22B`

**Pink Ribbon**
- Curved/winding SVG path in `#FF6DB3`
- Appears as a flowing band connecting sections on homepage
- Animated subtle motion on some pages

### Forms & Inputs

- Border: `1px solid rgba(32, 7, 7, 0.8)` (from WooCommerce form variables)
- Border-radius: `4px`
- Background: `#FFFFFF`
- Label: Rubik 14px weight 400, `#14093B`
- Placeholder: `#706A70`
- Focus: border color shifts to `#2473C8`

## 5. Layout Principles

### Spacing System
- Base unit: 10px
- Scale: 10px, 20px, 25px, 30px, 40px, 50px, 100px, 150px
- Section vertical padding: typically 80px–150px top and bottom
- Component internal padding: 20px–40px
- The scale is relatively simple — generous round numbers, not micro-precision

### Grid & Container
- Max content width: `1140px` (from `--container-max-width`)
- Wide content: `1200px` (from `--wp--style--global--wide-size`)
- Hero: full-viewport-width colored sections with internal centered content
- Feature sections: 2-column grid (50/50) for text + visual pairings
- Course cards: 2-column grid with CSS grid (`repeat(2, 1fr)`)
- Blog cards: 3-column grid at desktop
- Footer: single-column centered

### Whitespace Philosophy
- **Color as section separator**: Aimprove never uses a gray line or a gap to separate sections. Instead, each section has its own background color, and wave dividers provide the visual transition. Whitespace is structural but never the primary separator.
- **Generous body line-height**: Body text at line-height 2.0 creates natural breathing room within text blocks, reducing the need for margin between paragraphs.
- **Full-width sections as theatrical acts**: Each section occupies the full viewport width and is designed as a self-contained stage. The hero is the opening act (gold), the "honesty" section is the quiet middle, and the CTA sections are the energetic finale.

### Border Radius Scale
- Micro (2px): Form inputs, select elements
- Standard (6px): Small badges, tiny containers
- Card (10px): General content cards
- Featured (15px): Major cards, prominent containers, section panels
- Button (50px): All standard buttons — the pill is Aimprove's signature shape
- Nav Button (88px): Navigation CTA pill — slightly more extreme than standard buttons
- Circle (100%): Floating WhatsApp button, avatar circles, icon buttons

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat (0) | No shadow | Section backgrounds, hero areas, course cards |
| Ambient (1) | `rgba(0, 0, 0, 0.1) 0px 0px 10px 0px` | Subtle card lift on feature cards |
| Blue-Tinted (2) | `rgba(59, 115, 194, 0.15) 0px 0px 10px 0px` | Blog cards, elements near blue sections |
| Elevated (3) | `rgba(0, 0, 0, 0.2) 0px 0px 20px 0px` | Modals, floating panels, popovers |
| Deep (4) | `rgba(0, 0, 0, 0.3) 0px 10px 30px 0px` | Cart sidebar, sticky overlays |
| Focus (Ring) | `rgba(0, 0, 0, 0.5) 0px 0px 6px -6px` | Input focus state (inward shadow) |

**Shadow Philosophy**: Aimprove's shadow usage is minimal and purposeful. Course cards and hero sections use no shadow at all — their solid, saturated color backgrounds provide visual weight without depth tricks. Shadow appears primarily on interactive/hoverable elements (blog cards, organization feature panels) and floating UI elements (cart, modals). When shadows appear, they are soft and diffuse — never sharp or dramatic. The blue-tinted shadow (`rgba(59, 115, 194, 0.15)`) ties shadow depth back to the brand's blue accent, the same way Stripe uses its navy shadow formula.

## 7. Do's and Don'ts

### Do
- Use `#FFD747` gold as the hero background for the main homepage and brand-defining moments
- Use `#14093B` dark navy for ALL primary headings — not black, not dark gray — the warmth matters
- Apply pill-shaped buttons exclusively (border-radius 50px+) — this is Aimprove's most distinctive UI signature
- Use Rubik for every text element — no exceptions, no mixing with other fonts
- Add wave SVG dividers between section color changes — hard cuts break the organic feeling
- Include the cat mascot on page heroes, colored to match that page's hero background
- Use weight 800 for display/hero headlines and weight 400–700 for body — maximize contrast
- Apply RTL layout with `direction: rtl` at the root level for Hebrew pages
- Use per-page hero colors: gold (`#FFD747`) for home, blue (`#2473C8`) for courses, green (`#05905D`) for blog
- Use saturated solid background colors for section variety — Aimprove sections are always "chromatic", never just off-white variations

### Don't
- Don't use pure `#000000` black for any text — always use `#14093B` (navy) or `#333333` (body)
- Don't use small border-radius (4px–8px) on buttons — Aimprove buttons are pill-shaped, always
- Don't mix fonts — there is no secondary typeface in this system
- Don't use subtle color variations to separate sections — use distinct background colors and wave dividers
- Don't create shadows on colored-background cards (course cards) — the color itself is the container
- Don't use thin (weight 300–400) headlines — Aimprove's hero text is always weight 800, never whisper-weight
- Don't use letter-spacing manipulation — Rubik's natural spacing is the brand's voice
- Don't use the cat mascot without a solid color background — it requires contrast to read as white SVG
- Don't use cool-neutral grays as section backgrounds — every section should feel alive with color
- Don't use gradients as primary design elements — Aimprove uses flat solid colors, never gradient overlays

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Mobile | <480px | Single column, hero text scales to ~48px, stacked cards |
| Mobile Large | 480–767px | Standard mobile, full pill buttons, single column |
| Tablet | 768–1024px | 2-column grids begin, moderate padding reduction |
| Desktop | 1025–1800px | Full layout, 3-column blog, 2-column features |
| Large Desktop | >1800px | Centered content with generous margins |

### Touch Targets
- Buttons use generous padding (minimum 12px vertical) with pill shapes providing large tap areas
- Nav button at 21px font with 88px radius ensures easy tap
- Course cards: full-width tappable on mobile
- WhatsApp floating button: 56px diameter circle, always accessible
- Statistics boxes: tap-to-read, no interactive function

### Collapsing Strategy
- Hero: 74px display → ~48px on tablet → ~36px on mobile; weight 800 maintained throughout
- Navigation: visible "צור קשר" pill + hamburger → hamburger only below 768px
- Feature grids: 2-column → 1-column on mobile
- Blog grid: 3-column → 2-column tablet → 1-column mobile
- Course curriculum: 2-column grid → 1-column stack on mobile
- Wave dividers: scale responsively, maintain organic feel
- Floating shapes: hidden or reduced on mobile (decorative only)
- Section padding: 100px–150px → 60px–80px on tablet → 40px–50px on mobile

### Image Behavior
- Cat mascot: maintains SVG sharpness at all sizes, may reduce from ~280px to ~180px
- Green leaves: decorative, may be hidden below 768px
- Video thumbnails in gallery: 3-per-row → 2 → 1 stack
- Logo: SVG scales proportionally, minimum 120px width

## 9. Agent Prompt Guide

### Quick Color Reference
- Hero Background (Home): Gold Yellow (`#FFD747`)
- Hero Background (Course): Course Blue (`#2473C8`)
- Hero Background (Blog): Blog Green (`#05905D`)
- Primary Text / Dark Section: Dark Navy (`#14093B`)
- Main CTA Button: Mid Navy bg (`#1F1341`) + White text
- Secondary CTA Button: Gold Yellow bg (`#FFD747`) + Navy text (`#14093B`)
- Body Text: Dark Gray (`#333333`)
- Organization Section: Light Mint (`#E0F5ED`)
- Blog Card Background: Light Blue (`#F1F8FF`)
- Accent Green (organic): Bright Green (`#6BD22B`)
- Accent Pink (ribbon/vibe): Pink Magenta (`#FF6DB3`)
- Statistics / Counters: Purple (`#6762FF`)
- All headings color: Dark Navy (`#14093B`)

### Example Component Prompts
- "Create a hero section with `#FFD747` gold background. H1 at 74px Rubik weight 800, color `#14093B`, line-height 1.0. Subtitle at 22px Rubik weight 400, same color. Two pill buttons: primary dark (`#1F1341` bg, white text, 22px weight 700, 50px radius) and outlined (transparent bg, `1px solid #1F1341`, `#1F1341` text, 50px radius). Add green leaf SVG decorations at corners. Wave SVG divider at bottom transitioning to white."
- "Design a course curriculum card grid (2 columns). Each card: solid color background (`#A52756`, `#05905D`, `#6762FF`, `#FE6DB2`), white text, 15px border-radius, 30px padding. No shadow, no border. Title at 20px Rubik weight 700. Body at 16px weight 400, line-height 2.0."
- "Build a statistics counter box: `#6762FF` purple background, `#FFFFFF` text, 15px radius. Number at 56px Rubik weight 800. Label at 16px weight 400, rgba(255,255,255,0.8)."
- "Create navigation bar: white background on scroll. Right-aligned: logo SVG. Left-aligned: hamburger icon. Center-right: user icon. Far right: `צור קשר` pill button (`#1F1341` bg, white, 88px radius, 21px Rubik weight 700). Direction RTL."
- "Design a dark testimonial banner: `#1F1341` background, 15px border-radius. Quote text at 28px Rubik weight 700, white. No shadow. Add cat mascot SVG (white line art, ~200px) positioned right-of-text on dark background."
- "Create a blog post card: `#F1F8FF` background, 10px radius, `rgba(59, 115, 194, 0.15) 0px 0px 10px 0px` shadow. Title at 24px Rubik weight 800, `#14093B`. Body at 16px weight 400, line-height 2.0, `#333333`. Yellow CTA button at bottom: `#FFD747` bg, `#14093B` text, 62px radius, 16px font, weight 700."

### Iteration Guide
1. The first decision on any page: which hero color? Gold (home/brand), Blue (course/education), Green (blog/content)
2. Every section needs a distinct background — no two adjacent sections should share a color
3. Wave dividers are mandatory between colored sections — generate as SVG `path` with organic curves
4. Buttons are always pill-shaped (50px+ radius) — no exceptions in the Aimprove design language
5. Rubik weight 800 for all display/hero text; weight 400 for body; weight 700 for buttons and H3
6. RTL direction must be set at root — use `direction: rtl; text-align: right` on `body`
7. The cat mascot needs a solid colored background — it is always white SVG on color, never on white/gray
8. Floating decorative shapes (colored squares at rotation) add energy to transitions — include 2–3 per major section break
9. Never use the same section color twice on a page — variety is structural, not decorative
10. Logo assets: white SVG for dark/colored backgrounds (`logo-improve-white.svg`); request dark version for white backgrounds
