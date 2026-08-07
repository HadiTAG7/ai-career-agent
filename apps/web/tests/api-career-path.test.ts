import { afterEach, describe, expect, it, vi } from "vitest";

const workspace = {
  provider_ready: true,
  provider: "openai",
  model: "gpt-test",
  profile_id: "profile-1",
  confirmed_fact_count: 4,
  consent_required: true,
  conversation: null,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("career path API client", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("uses the documented GET, POST, and DELETE contracts without a demo fallback", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const responseWorkspace = {
      ...workspace,
      consent_required: false,
      conversation: { id: "conversation-1", revision: 1, messages: [] },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(workspace))
      .mockResolvedValueOnce(jsonResponse(responseWorkspace))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const { deleteCareerPathConversation, getCareerPathWorkspace, sendCareerPathMessage, setApiTokenGetter } = await import("@/lib/api-client");
    setApiTokenGetter(async () => "career-path-token");

    await expect(getCareerPathWorkspace()).resolves.toEqual(workspace);
    await expect(sendCareerPathMessage({
      content: "I enjoy analysis",
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      expected_revision: 0,
      data_sharing_acknowledged: true,
    })).resolves.toEqual(responseWorkspace);
    await expect(deleteCareerPathConversation()).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[0][0])).toBe("https://api.test/v1/career-path");
    expect(String(fetchMock.mock.calls[1][0])).toBe("https://api.test/v1/career-path/messages");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      content: "I enjoy analysis",
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      expected_revision: 0,
      data_sharing_acknowledged: true,
    });
    expect(String(fetchMock.mock.calls[2][0])).toBe("https://api.test/v1/career-path/conversation");
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "DELETE" });
    for (const call of fetchMock.mock.calls) expect((call[1]?.headers as Headers).get("Authorization")).toBe("Bearer career-path-token");
  });

  it("preserves the server error code without exposing the raw error object", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: "ai_provider_unavailable",
        message: "The career path assistant is temporarily unavailable",
        request_id: "request-123",
      },
    }, 503)));
    const { ApiHttpError, apiErrorMessage, sendCareerPathMessage } = await import("@/lib/api-client");

    const failure = await sendCareerPathMessage({
      content: "I enjoy analysis",
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      expected_revision: 0,
      data_sharing_acknowledged: true,
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiHttpError);
    expect(failure).toMatchObject({ status: 503, code: "ai_provider_unavailable", requestId: "request-123" });
    expect(apiErrorMessage(failure, "en")).toContain("temporarily unavailable");
  });
});
