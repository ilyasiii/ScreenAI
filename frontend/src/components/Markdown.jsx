/**
 * Markdown for model-generated answers.
 *
 * Answers are untrusted: text on the captured screen can steer what the model
 * writes. react-markdown already refuses raw HTML and javascript: URLs; on top
 * of that, links open in a new tab with no opener and no referrer, so a link in
 * an answer can neither replace the app nor script the page that opened it.
 */
import ReactMarkdown from "react-markdown";

function SafeLink({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  );
}

const COMPONENTS = { a: SafeLink };

export default function Markdown({ children }) {
  return <ReactMarkdown components={COMPONENTS}>{children}</ReactMarkdown>;
}
