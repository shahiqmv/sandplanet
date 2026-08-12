import { useEffect, useRef, useState } from "react";

/* A WebRTC player for one camera, spoken in WHEP (WebRTC-HTTP Egress).
 *
 * The app never hands the browser a lasting credential: `getTicket` is called
 * fresh on every connect and returns a ticket good for about ninety seconds,
 * which is long enough to negotiate and useless afterwards. It travels in an
 * Authorization header rather than the URL so it stays out of browser history,
 * proxy logs and Referer headers.
 *
 * WebRTC (not HLS) because HLS buffers ~13s — long enough that a live view of
 * a site feels broken.
 */
export default function WhepPlayer({ getTicket, poster, onError }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const resourceRef = useRef(null);
  const [state, setState] = useState("idle");   // idle|connecting|live|error
  const [msg, setMsg] = useState("");

  useEffect(() => () => teardown(), []);        // always release the camera

  function teardown() {
    // Tell the relay we are done; without this the source stays up until its
    // idle timer fires, which on a metered island uplink is real money.
    const res = resourceRef.current;
    if (res) {
      fetch(res, { method: "DELETE" }).catch(() => {});
      resourceRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
  }

  async function connect() {
    setState("connecting");
    setMsg("");
    try {
      const { whep, ticket } = await getTicket();
      if (!whep) throw new Error("No camera relay is configured yet.");

      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pcRef.current = pc;
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });
      pc.ontrack = (e) => {
        if (videoRef.current) videoRef.current.srcObject = e.streams[0];
      };
      pc.onconnectionstatechange = () => {
        if (!pcRef.current) return;
        if (pc.connectionState === "connected") setState("live");
        if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
          setState("error");
          setMsg("The connection to the camera dropped.");
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await gathered(pc);

      const r = await fetch(whep, {
        method: "POST",
        headers: {
          "Content-Type": "application/sdp",
          Authorization: "Basic " + btoa("ticket:" + ticket),
        },
        body: pc.localDescription.sdp,
      });
      if (!r.ok) {
        throw new Error(r.status === 401
          ? "The relay refused this view request."
          : `The relay answered ${r.status}.`);
      }
      resourceRef.current = r.headers.get("Location") || null;
      const answer = await r.text();
      await pc.setRemoteDescription({ type: "answer", sdp: answer });
    } catch (e) {
      teardown();
      setState("error");
      setMsg(e.message || "Could not open the camera.");
      if (onError) onError(e);
    }
  }

  function stop() {
    teardown();
    if (videoRef.current) videoRef.current.srcObject = null;
    setState("idle");
  }

  return (
    <div className="whep">
      <div className="whep-frame">
        <video ref={videoRef} autoPlay playsInline muted
               poster={poster || undefined}
               style={{ display: state === "live" ? "block" : "none" }} />
        {state !== "live" && (
          <div className="whep-overlay">
            {state === "connecting" && <p>Connecting to the camera…</p>}
            {state === "idle" && (
              <button className="btn primary" onClick={connect}>
                ▶ Watch live
              </button>
            )}
            {state === "error" && (
              <>
                <p className="whep-err">{msg}</p>
                <button className="btn" onClick={connect}>Try again</button>
              </>
            )}
          </div>
        )}
      </div>
      {state === "live" && (
        <div className="whep-bar">
          <span className="whep-dot" /> Live
          <button className="btn" onClick={stop}>Stop</button>
        </div>
      )}
    </div>
  );
}

/* Wait for ICE candidates before offering. MediaMTX accepts a non-trickle
 * offer, and gathering on a LAN finishes in well under the timeout — the cap
 * just stops a hostile network from hanging the page. */
function gathered(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === "complete") done();
    };
    pc.addEventListener("icegatheringstatechange", check);
    setTimeout(done, 2000);
  });
}
