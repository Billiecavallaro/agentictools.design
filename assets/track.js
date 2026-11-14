/* Click events for Google Analytics (the gtag snippet is in each page's <head>).
   outbound_click        a click to another site; agent_name comes from data-agent
   subscribe_click       a click on any "Subscribe" / "Get the weekly email" link
   newsletter_form_click a click into the Substack signup form (it's an iframe,
                         so this fires when it takes focus, once per page view)
   sponsor_email_copy    the "Copy email address" button in Sponsor a spot
   Static file: scripts/build.py doesn't touch it. */
(function(){
  "use strict";
  function send(name, params){
    if (typeof window.gtag !== "function") return;
    params = params || {};
    params.page_path = location.pathname;
    window.gtag("event", name, params);
  }

  document.addEventListener("click", function(ev){
    var t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest("#sponsorCopy")) { send("sponsor_email_copy"); return; }
    var a = t.closest("a[href]");
    if (!a) return;
    var u;
    try { u = new URL(a.getAttribute("href"), location.href); } catch(e){ return; }
    if (u.hash === "#subscribe" && u.host === location.host) {
      send("subscribe_click", {link_text: (a.textContent || "").trim().slice(0, 60)});
      return;
    }
    if ((u.protocol === "https:" || u.protocol === "http:") && u.host !== location.host) {
      send("outbound_click", {
        agent_name: a.getAttribute("data-agent") || u.hostname.replace(/^www\./, ""),
        link_url: u.origin + u.pathname,
        link_domain: u.hostname
      });
    }
  }, true);

  // Clicks inside the Substack iframe never reach this page. When the page loses
  // focus to that iframe, the visitor has clicked into the signup form.
  var formSent = false;
  window.addEventListener("blur", function(){
    setTimeout(function(){
      var f = document.activeElement;
      if (!formSent && f && f.tagName === "IFRAME" && /substack\.com/.test(f.src || "")) {
        formSent = true;
        send("newsletter_form_click");
      }
    }, 0);
  });
})();
