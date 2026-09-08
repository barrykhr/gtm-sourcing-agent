// Port of resume_extraction.py -- turns an uploaded PDF/DOCX/TXT file
// into plain text, which then goes through the exact same
// candidate_analysis flow a pasted-text "add candidate" already uses.
// Extraction only, no field parsing here.
import pdfParse from "pdf-parse";
import mammoth from "mammoth";

export const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt"] as const;

export async function extractText(filename: string, content: Buffer): Promise<string> {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".pdf")) {
    const data = await pdfParse(content);
    return data.text;
  }
  if (lower.endsWith(".docx")) {
    const result = await mammoth.extractRawText({ buffer: content });
    return result.value;
  }
  if (lower.endsWith(".txt")) {
    return content.toString("utf-8");
  }
  throw new Error(`unsupported file type: '${filename}' — upload a ${SUPPORTED_EXTENSIONS.join(", ")} file`);
}
