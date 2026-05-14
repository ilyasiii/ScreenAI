/**
 * ScreenAI — SaaS Landing Page
 * Conversion-focused B2B landing with all sections
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import "./LandingPage.css";

/* ── Reusable SVG Icons ── */
const Icons = {
  monitor: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  ),
  zap: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  ),
  eye: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  layers: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" />
    </svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  code: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  globe: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="check">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  cross: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="cross">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  chevronDown: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  ),
  star: (
    <svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  ),
  arrowRight: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  menu: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  ),
};

/* ══════════════════════════════════════════════════════════════════ */

export default function LandingPage() {
  const [annualBilling, setAnnualBilling] = useState(true);
  const [openFaq, setOpenFaq] = useState(0);
  const [formData, setFormData] = useState({
    firstName: "", lastName: "", email: "", company: "", teamSize: "", message: "",
  });

  const handleFormChange = (e) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    alert("Demo request submitted! We'll be in touch.");
    setFormData({ firstName: "", lastName: "", email: "", company: "", teamSize: "", message: "" });
  };

  return (
    <div className="landing">

      {/* ════════ NAVIGATION ════════ */}
      <nav className="landing-nav">
        <div className="nav-inner">
          <a href="#" className="nav-logo">
            <div className="nav-logo-icon">{Icons.monitor}</div>
            <span className="nav-logo-text">ScreenAI</span>
          </a>

          <ul className="nav-links">
            <li>
              <button className="nav-link">
                Product {Icons.chevronDown}
              </button>
              <div className="nav-dropdown">
                <a href="#features" className="dropdown-item">
                  Features <span>AI-powered screen reading</span>
                </a>
                <a href="#solutions" className="dropdown-item">
                  Solutions <span>For teams and enterprises</span>
                </a>
              </div>
            </li>
            <li><a href="#pricing" className="nav-link">Pricing</a></li>
            <li><a href="#faq" className="nav-link">Resources</a></li>
            <li><a href="#testimonials" className="nav-link">About</a></li>
            <li><a href="#contact" className="nav-link">Contact</a></li>
          </ul>

          <div className="nav-actions">
            <Link to="/auth" className="btn-ghost">Log in</Link>
            <a href="#contact" className="btn-landing btn-primary-landing">
              Book a Demo
            </a>
          </div>

          <button className="nav-hamburger">{Icons.menu}</button>
        </div>
      </nav>

      {/* ════════ HERO ════════ */}
      <section className="hero">
        <div className="landing-container">
          <div className="hero-badge">
            <span className="hero-badge-dot"></span>
            Now with real-time streaming — 3x faster responses
          </div>

          <h1>
            AI That <span className="gradient-text">Reads Your Screen</span><br />
            And Solves Problems Instantly
          </h1>

          <p className="hero-subtitle">
            ScreenAI watches your screen in real-time and provides instant answers to
            coding problems, exam questions, technical docs, and anything else visible
            on your display.
          </p>

          <div className="hero-actions">
            <a href="#contact" className="btn-landing btn-primary-landing btn-large-landing">
              Book a Demo {Icons.arrowRight}
            </a>
            <Link to="/auth" className="btn-landing btn-secondary-landing btn-large-landing">
              Try Free {Icons.play}
            </Link>
          </div>

          <p className="hero-note">No credit card required · Free tier available · Setup in 2 minutes</p>

          {/* Product Screenshot Mockup */}
          <div className="hero-visual">
            <div className="hero-screenshot">
              <div className="screenshot-header">
                <span className="screenshot-dot red"></span>
                <span className="screenshot-dot yellow"></span>
                <span className="screenshot-dot green"></span>
                <span className="screenshot-url">app.screenai.com</span>
              </div>
              <div className="screenshot-body">
                <div className="screenshot-mockup">
                  <div className="mockup-left">
                    <div className="mockup-bar short accent"></div>
                    <div className="mockup-video-area">
                      {Icons.monitor}
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <div className="mockup-bar medium accent" style={{ flex: 1 }}></div>
                      <div className="mockup-bar short" style={{ flex: 0.6 }}></div>
                    </div>
                  </div>
                  <div className="mockup-right">
                    <div className="mockup-bar short accent"></div>
                    <div className="mockup-card">
                      <div className="mockup-bar long"></div>
                      <div className="mockup-bar medium"></div>
                      <div className="mockup-bar long"></div>
                      <div className="mockup-bar short"></div>
                    </div>
                    <div className="mockup-card">
                      <div className="mockup-bar medium accent"></div>
                      <div className="mockup-bar long"></div>
                      <div className="mockup-bar long"></div>
                      <div className="mockup-bar medium"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="hero-glow"></div>
          </div>
        </div>
      </section>

      {/* ════════ LOGO BAR ════════ */}
      <section className="logo-bar">
        <div className="landing-container">
          <p className="logo-bar-label">Trusted by teams at</p>
          <div className="logo-bar-logos">
            {["TechCorp", "DevStudio", "CloudBase", "CodeLab", "DataFlow"].map((name) => (
              <div key={name} className="logo-placeholder">
                <div className="logo-dot"></div>
                {name}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════ FEATURES ════════ */}
      <section className="features" id="features">
        <div className="landing-container">
          <div className="features-header">
            <div className="section-label">Features</div>
            <h2 className="section-title">Everything you need to solve problems faster</h2>
            <p className="section-subtitle">
              From real-time screen analysis to multi-context support, ScreenAI
              gives you superpowers for any visual problem.
            </p>
          </div>

          <div className="features-grid">
            {[
              { icon: Icons.eye, title: "Real-Time Screen Reading", desc: "AI analyzes your screen instantly. Share any window, tab, or full screen and get answers in seconds." },
              { icon: Icons.zap, title: "Streaming Responses", desc: "Watch answers appear word-by-word in real-time. No more waiting for the full response to load." },
              { icon: Icons.layers, title: "Multi-Screen Context", desc: "Scroll through long problems and add screenshots as context. AI combines all screens for a complete answer." },
              { icon: Icons.code, title: "Code Solutions", desc: "Detects coding problems automatically and provides complete, ready-to-submit code solutions." },
              { icon: Icons.shield, title: "Privacy First", desc: "Screenshots are processed in-memory and never stored. Your screen data stays private and secure." },
              { icon: Icons.globe, title: "Works Everywhere", desc: "Browser-based — works on any OS, any device. No downloads, no extensions, no setup required." },
            ].map((f, i) => (
              <div key={i} className="feature-card">
                <div className="feature-icon">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════ SOLUTIONS / HOW IT WORKS ════════ */}
      <section className="solutions" id="solutions">
        <div className="landing-container">
          <div className="section-label">How it works</div>
          <h2 className="section-title">Three steps to instant answers</h2>

          <div className="solutions-grid">
            <div className="solutions-content">
              {[
                { num: "01", title: "Share Your Screen", desc: "Click one button to share your screen, window, or browser tab. Works in any modern browser." },
                { num: "02", title: "Ask or Auto-Detect", desc: "Type a specific question or let the AI automatically detect problems on screen — MCQs, code, essays, anything." },
                { num: "03", title: "Get Instant Answers", desc: "AI reads the screen and streams a precise answer in real-time. Code solutions, explanations, or direct answers." },
              ].map((s, i) => (
                <div key={i} className="solution-item">
                  <div className="solution-num">{s.num}</div>
                  <div>
                    <h4>{s.title}</h4>
                    <p>{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="solutions-visual">
              <div className="stats-grid">
                <div className="stat-card">
                  <div className="stat-value">{"<"}2s</div>
                  <div className="stat-label">First token response</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">95%</div>
                  <div className="stat-label">Accuracy rate</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">50+</div>
                  <div className="stat-label">Languages supported</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">10x</div>
                  <div className="stat-label">Faster problem solving</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ════════ PRICING ════════ */}
      <section className="pricing" id="pricing">
        <div className="landing-container">
          <div className="pricing-header">
            <div className="section-label">Pricing</div>
            <h2 className="section-title">Simple, transparent pricing</h2>
            <p className="section-subtitle">
              Start free and scale as you grow. No hidden fees, cancel anytime.
            </p>
            <div className="pricing-toggle">
              <span className={!annualBilling ? "active" : ""}>Monthly</span>
              <div
                className={`toggle-switch${annualBilling ? " toggled" : ""}`}
                onClick={() => setAnnualBilling(!annualBilling)}
                role="button"
                tabIndex={0}
              />
              <span className={annualBilling ? "active" : ""}>Annual</span>
              <span className="save-badge">Save 20%</span>
            </div>
          </div>

          <div className="pricing-cards">
            {/* Free */}
            <div className="pricing-card">
              <div className="pricing-card-header">
                <h3>Starter</h3>
                <p>For individuals getting started</p>
              </div>
              <div className="pricing-price">
                <span className="currency">$</span>
                <span className="amount">0</span>
                <span className="period">/month</span>
              </div>
              <ul className="pricing-features">
                <li>{Icons.check} 20 screen analyses / day</li>
                <li>{Icons.check} Real-time streaming</li>
                <li>{Icons.check} Code detection</li>
                <li>{Icons.cross} Multi-screen context</li>
                <li>{Icons.cross} Priority support</li>
                <li>{Icons.cross} Team collaboration</li>
              </ul>
              <Link to="/auth" className="btn-landing btn-secondary-landing">
                Get Started Free
              </Link>
            </div>

            {/* Pro */}
            <div className="pricing-card featured">
              <div className="popular-badge">Most Popular</div>
              <div className="pricing-card-header">
                <h3>Pro</h3>
                <p>For professionals and power users</p>
              </div>
              <div className="pricing-price">
                <span className="currency">$</span>
                <span className="amount">{annualBilling ? "19" : "24"}</span>
                <span className="period">/month</span>
              </div>
              <ul className="pricing-features">
                <li>{Icons.check} Unlimited analyses</li>
                <li>{Icons.check} Real-time streaming</li>
                <li>{Icons.check} Code detection</li>
                <li>{Icons.check} Multi-screen context (10 screenshots)</li>
                <li>{Icons.check} Priority support</li>
                <li>{Icons.cross} Team collaboration</li>
              </ul>
              <a href="#contact" className="btn-landing btn-primary-landing">
                Start Pro Trial
              </a>
            </div>

            {/* Enterprise */}
            <div className="pricing-card">
              <div className="pricing-card-header">
                <h3>Enterprise</h3>
                <p>For teams and organizations</p>
              </div>
              <div className="pricing-price">
                <span className="currency">$</span>
                <span className="amount">{annualBilling ? "49" : "59"}</span>
                <span className="period">/seat/month</span>
              </div>
              <ul className="pricing-features">
                <li>{Icons.check} Everything in Pro</li>
                <li>{Icons.check} Unlimited context</li>
                <li>{Icons.check} Team collaboration</li>
                <li>{Icons.check} Admin dashboard</li>
                <li>{Icons.check} SSO & SAML</li>
                <li>{Icons.check} Dedicated support</li>
              </ul>
              <a href="#contact" className="btn-landing btn-secondary-landing">
                Contact Sales
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ════════ TESTIMONIALS ════════ */}
      <section className="testimonials" id="testimonials">
        <div className="landing-container">
          <div className="testimonials-header">
            <div className="section-label">Testimonials</div>
            <h2 className="section-title">Loved by developers worldwide</h2>
            <p className="section-subtitle">
              See what our users say about how ScreenAI transformed their workflow.
            </p>
          </div>

          <div className="testimonials-slider">
            {[
              {
                text: "ScreenAI completely changed how I study. I just share my screen and it instantly solves any problem I'm looking at. Absolute game changer.",
                name: "Sarah Chen",
                role: "CS Student, Stanford",
                initials: "SC",
              },
              {
                text: "We integrated ScreenAI into our QA workflow. The ability to read any screen and provide context-aware answers saved our team hours every day.",
                name: "Mark Rivera",
                role: "QA Lead, TechCorp",
                initials: "MR",
              },
              {
                text: "The streaming feature is incredible. Answers start appearing in under 2 seconds. It feels like having a senior developer watching your screen 24/7.",
                name: "Alex Kim",
                role: "Full-Stack Developer",
                initials: "AK",
              },
            ].map((t, i) => (
              <div key={i} className="testimonial-card">
                <div className="testimonial-stars">
                  {[...Array(5)].map((_, j) => <span key={j}>{Icons.star}</span>)}
                </div>
                <p className="testimonial-text">"{t.text}"</p>
                <div className="testimonial-author">
                  <div className="testimonial-avatar">{t.initials}</div>
                  <div className="testimonial-info">
                    <h4>{t.name}</h4>
                    <p>{t.role}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════ FAQ ════════ */}
      <section className="faq" id="faq">
        <div className="landing-container">
          <div className="faq-header">
            <div className="section-label">FAQ</div>
            <h2 className="section-title">Frequently asked questions</h2>
            <p className="section-subtitle">
              Can't find what you're looking for? Contact our support team.
            </p>
          </div>

          <div className="faq-list">
            {[
              {
                q: "How does ScreenAI read my screen?",
                a: "ScreenAI uses your browser's built-in Screen Capture API. When you click 'Share Screen', your browser asks for permission, then ScreenAI captures frames and sends them to our AI for analysis. No downloads or extensions needed.",
              },
              {
                q: "Is my screen data stored or shared?",
                a: "No. Screenshots are processed in-memory and immediately discarded after analysis. We never store, log, or share your screen data. Your privacy is our top priority.",
              },
              {
                q: "What types of problems can it solve?",
                a: "ScreenAI handles coding problems (LeetCode, HackerRank, etc.), multiple-choice questions, written/essay questions, technical documentation, math problems, and more. If it's visible on your screen, ScreenAI can analyze it.",
              },
              {
                q: "Which programming languages are supported?",
                a: "ScreenAI supports 50+ programming languages including Python, JavaScript, TypeScript, C++, Java, Go, Rust, C#, and more. It automatically detects the language from your screen.",
              },
              {
                q: "Can I use it for exams or interviews?",
                a: "ScreenAI is a learning and productivity tool. We encourage ethical use — it's great for studying, practicing problems, and learning from solutions. Please follow your institution's academic integrity policies.",
              },
              {
                q: "What's the multi-screen context feature?",
                a: "For long questions that span multiple screens, you can capture screenshots as 'context' before analyzing. ScreenAI combines all context screenshots to understand the complete problem before answering.",
              },
            ].map((item, i) => (
              <div key={i} className={`faq-item${openFaq === i ? " open" : ""}`}>
                <button className="faq-question" onClick={() => setOpenFaq(openFaq === i ? -1 : i)}>
                  {item.q}
                  {Icons.chevronDown}
                </button>
                <div className="faq-answer">
                  <p>{item.a}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════ CTA / DEMO FORM ════════ */}
      <section className="cta-section" id="contact">
        <div className="landing-container">
          <div className="cta-inner">
            <div className="section-label">Get Started</div>
            <h2 className="section-title">Ready to solve problems 10x faster?</h2>
            <p className="section-subtitle">
              Book a demo or start your free trial today. No credit card required.
            </p>

            <form className="demo-form" onSubmit={handleFormSubmit}>
              <h3>Book a Demo</h3>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="firstName">First Name</label>
                  <input type="text" id="firstName" name="firstName" placeholder="John" value={formData.firstName} onChange={handleFormChange} required />
                </div>
                <div className="form-group">
                  <label htmlFor="lastName">Last Name</label>
                  <input type="text" id="lastName" name="lastName" placeholder="Doe" value={formData.lastName} onChange={handleFormChange} required />
                </div>
              </div>
              <div className="form-group">
                <label htmlFor="email">Work Email</label>
                <input type="email" id="email" name="email" placeholder="john@company.com" value={formData.email} onChange={handleFormChange} required />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="company">Company</label>
                  <input type="text" id="company" name="company" placeholder="Acme Inc." value={formData.company} onChange={handleFormChange} />
                </div>
                <div className="form-group">
                  <label htmlFor="teamSize">Team Size</label>
                  <select id="teamSize" name="teamSize" value={formData.teamSize} onChange={handleFormChange}>
                    <option value="">Select...</option>
                    <option value="1-5">1–5</option>
                    <option value="6-20">6–20</option>
                    <option value="21-50">21–50</option>
                    <option value="51-200">51–200</option>
                    <option value="200+">200+</option>
                  </select>
                </div>
              </div>
              <div className="form-group full">
                <label htmlFor="message">Message (optional)</label>
                <textarea id="message" name="message" placeholder="Tell us about your use case..." value={formData.message} onChange={handleFormChange} rows={3} />
              </div>
              <button type="submit" className="btn-landing btn-primary-landing btn-large-landing">
                Submit Demo Request {Icons.arrowRight}
              </button>
              <p className="form-note">We'll get back to you within 24 hours</p>
            </form>
          </div>
        </div>
      </section>

      {/* ════════ FOOTER ════════ */}
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="footer-grid">
            <div className="footer-brand">
              <div className="nav-logo">
                <div className="nav-logo-icon">{Icons.monitor}</div>
                <span className="nav-logo-text">ScreenAI</span>
              </div>
              <p>AI-powered screen reading that solves problems instantly. Built for developers, students, and teams.</p>
            </div>
            <div className="footer-col">
              <h4>Product</h4>
              <ul>
                <li><a href="#features">Features</a></li>
                <li><a href="#solutions">Solutions</a></li>
                <li><a href="#pricing">Pricing</a></li>
                <li><a href="#faq">FAQ</a></li>
              </ul>
            </div>
            <div className="footer-col">
              <h4>Company</h4>
              <ul>
                <li><a href="#testimonials">About</a></li>
                <li><a href="#contact">Contact</a></li>
                <li><a href="#">Careers</a></li>
                <li><a href="#">Blog</a></li>
              </ul>
            </div>
            <div className="footer-col">
              <h4>Legal</h4>
              <ul>
                <li><a href="#">Privacy Policy</a></li>
                <li><a href="#">Terms of Service</a></li>
                <li><a href="#">Cookie Policy</a></li>
                <li><a href="#">GDPR</a></li>
              </ul>
            </div>
          </div>
          <div className="footer-bottom">
            <p>&copy; {new Date().getFullYear()} ScreenAI. All rights reserved.</p>
            <div className="footer-socials">
              <a href="#" aria-label="Twitter">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 4s-.7 2.1-2 3.4c1.6 10-9.4 17.3-18 11.6 2.2.1 4.4-.6 6-2C3 15.5.5 9.6 3 5c2.2 2.6 5.6 4.1 9 4-.9-4.2 4-6.6 7-3.8 1.1 0 3-1.2 3-1.2z"/></svg>
              </a>
              <a href="#" aria-label="GitHub">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg>
              </a>
              <a href="#" aria-label="LinkedIn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg>
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
