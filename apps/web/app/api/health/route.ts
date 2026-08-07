import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json({ status: "ok", service: "ai-career-agent-web" });
}
