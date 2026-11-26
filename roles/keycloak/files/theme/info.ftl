<#--
  Keycloak's own info page (theme/base/login/info.ftl of 26.8), with its
  "Back to Application" links replaced by a link to Antares-Web.

  Antares-Web does not speak OIDC, so Keycloak has no application of its own
  to send anyone back to. Left alone, the page shows either no link at all
  (skipLink: every link an administrator mails from the console, which never
  passes a redirect_uri) or a link to the base URL of a Keycloak client,
  which lands on a Keycloak login page. A member who just set a password
  wants Antares-Web. "Click here to proceed", which finishes an action still
  under way, is kept.

  Deployed by the playbook (roles/keycloak/tasks/theme.yml); edit it there.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        <#if messageHeader??>
            ${kcSanitize(msg("${messageHeader}"))?no_esc}
        <#else>
            ${message.summary}
        </#if>
    <#elseif section = "form">
    <div id="kc-info-message">
        <p class="instruction">${message.summary}<#if requiredActions??><#list requiredActions>: <b><#items as reqActionItem>${kcSanitize(msg("requiredAction.${reqActionItem}"))?no_esc}<#sep>, </#items></b></#list><#else></#if></p>
        <#if !(skipLink??) && actionUri?has_content>
            <p><a href="${actionUri}">${msg("proceedWithAction")}</a></p>
        <#elseif properties.antaresAppUrl?has_content>
            <p><a id="antares-app-link" href="${properties.antaresAppUrl}">${msg("antaresOpenApp")}</a></p>
        </#if>
    </div>
    </#if>
</@layout.registrationLayout>
