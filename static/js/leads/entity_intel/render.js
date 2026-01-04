/**
 * Entity Intelligence Display Component
 * Renders GPT analysis results for lead entity intelligence
 */

(function() {
  'use strict';

  // Helper functions for formatting
  function formatEntityStatus(status) {
    if (!status) return "—";
    const statusMap = {
      "Active/Compliance": "Active",
      "Admin. Dissolved": "Admin Dissolved",
      "Dissolved": "Dissolved",
      "Withdrawn": "Withdrawn",
      "Reinstated": "Reinstated",
    };
    return statusMap[status] || status;
  }

  function formatRelationshipType(type) {
    if (!type || type === "none") return null;
    const typeMap = {
      "subsidiary": "Subsidiary",
      "affiliate": "Affiliate",
      "division": "Division",
      "brand_or_capability": "Brand/Capability",
      "branch_office": "Branch Office",
      "unknown": "Unknown Relationship",
    };
    return typeMap[type] || type;
  }

  function formatOutcome(outcome) {
    if (!outcome) return "—";
    const outcomeMap = {
      "identified_business_entity": "Identified Business Entity",
      "identified_successor_entity": "Identified Successor Entity",
      "identified_parent_outreach_entity": "Identified Parent Entity",
      "person_entitlement_likely": "Person Entitlement Likely",
      "multiple_candidates": "Multiple Candidates",
      "not_identified": "Not Identified",
    };
    return outcomeMap[outcome] || outcome;
  }

  function formatGoogleBusinessStatus(status) {
    if (!status) return "—";
    const statusMap = {
      "open": "Open",
      "temporarily_closed": "Temporarily Closed",
      "permanently_closed": "Permanently Closed",
      "unknown": "Unknown",
    };
    return statusMap[status] || status;
  }

  function formatPreferredOutreachMethod(method) {
    if (!method || method === "unknown") return "—";
    const methodMap = {
      "mail": "Mail",
      "phone": "Phone",
      "email": "Email",
      "web_form": "Web Form",
    };
    return methodMap[method] || method;
  }

  function formatContactType(type) {
    if (!type) return "—";
    const typeMap = {
      "employee": "Employee",
      "owner": "Owner",
      "agent": "Agent",
      "agent_business": "Agent Business",
      "other": "Other",
    };
    return typeMap[type] || type;
  }

  function formatRoleBucket(bucket) {
    if (!bucket) return "—";
    const bucketMap = {
      "unclaimed_property": "Unclaimed Property",
      "treasury": "Treasury",
      "controller": "Controller",
      "chief_accounting": "Chief Accounting",
      "accounts_payable": "Accounts Payable",
      "finance": "Finance",
      "legal": "Legal",
      "executive": "Executive",
      "owner": "Owner",
      "registered_agent": "Registered Agent",
      "other": "Other",
    };
    return bucketMap[bucket] || bucket;
  }

  function formatSource(source) {
    if (!source) return "—";
    const sourceMap = {
      "ga_sos": "GA SOS",
      "web": "Web",
      "google_business": "Google Business",
      "derived": "Derived",
    };
    return sourceMap[source] || source;
  }

  function formatTemplateCategory(category) {
    if (!category) return "—";
    const categoryMap = {
      "active_standard": "Active Standard",
      "active_large_corporate": "Active Large Corporate",
      "dissolved_or_inactive": "Dissolved/Inactive",
      "withdrawn_foreign": "Withdrawn Foreign",
      "successor_or_rename": "Successor/Rename",
      "subsidiary_or_parent_outreach": "Subsidiary/Parent Outreach",
      "multiple_candidates_manual_review": "Multiple Candidates (Manual Review)",
      "not_identified": "Not Identified",
    };
    return categoryMap[category] || category;
  }

  function extractYearFromDate(dateStr) {
    if (!dateStr) return null;
    try {
      const date = new Date(dateStr);
      return date.getFullYear();
    } catch (e) {
      // Try to extract year from string
      const match = dateStr.match(/\d{4}/);
      return match ? parseInt(match[0]) : null;
    }
  }

  function renderResult(container, data, selectedSosData) {
    if (!data || !data.analysis) {
      container.classList.add("error-state");
      container.innerHTML = "No insights returned. Try again later.";
      return;
    }

    const analysis = data.analysis;
    const selectedSos = selectedSosData || data.selected_sos_data || analysis.context_inputs?.ga_sos_selected_record || null;
    
    // Detect schema version and extract fields flexibly
    const queryContext = analysis.query_context || {};
    const contextInputs = analysis.context_inputs || {};
    const hypotheses = analysis.hypotheses || [];
    const selectedEntitledEntity = analysis.selected_entitled_entity || {};
    
    // Legacy schema fields (for backward compatibility)
    const identification = analysis.identification || {};
    const relationship = analysis.relationship || {};
    const addresses = analysis.addresses || {};
    const businessChannels = analysis.business_channels || {};
    const peopleContacts = analysis.people_contacts || {};
    const integrationFlags = analysis.integration_flags || {};
    const dataGaps = analysis.data_gaps || {};
    const changeProfile = analysis.change_profile || {};
    const communicationProfile = analysis.communication_profile || {};

    container.classList.remove("empty-state", "error-state");

    // Determine if we're using new schema (v12) or legacy schema
    const isNewSchema = !!analysis.hypotheses && !!analysis.selected_entitled_entity;
    
    // 1. SOS BUSINESS ENTITY DETAILS
    // Use context_inputs.ga_sos_selected_record if available (new schema), otherwise fallback
    const sosRecordForDisplay = contextInputs.ga_sos_selected_record || selectedSos || {};
    const originalGAEntity = identification.original_ga_entity || sosRecordForDisplay || {};
    const originalEntityName = originalGAEntity.legal_name || originalGAEntity.business_name || "—";
    const originalEntityStatus = formatEntityStatus(originalGAEntity.entity_status);
    const originalEntityStatusDate = originalGAEntity.entity_status_date;
    const originalEntityLastYear = extractYearFromDate(originalEntityStatusDate);
    
    // Relationship information (legacy schema - may not exist in new schema)
    const relationshipType = formatRelationshipType(relationship.relationship_type);
    const isCentralized = relationship.centralized_unclaimed_property_likely;
    
    // Change profile flags (legacy schema - may not exist in new schema)
    const isRenamed = changeProfile.has_name_change_or_rebrand;
    const isMerged = changeProfile.has_merger_or_acquisition;
    const hasSuccessor = changeProfile.has_successor_entity;
    const successorName = changeProfile.successor_entity_name;
    const isWithdrawn = changeProfile.is_withdrawn_from_ga;
    const isDissolved = changeProfile.is_dissolved_or_admin_dissolved;
    const isReinstated = changeProfile.is_reinstated;

    // Always show SOS section if we have query context or original entity data
    const sosContacts = [];
    if (selectedSos) {
      if (selectedSos.registered_agent) {
        sosContacts.push({
          label: "Registered Agent",
          name: selectedSos.registered_agent.name || "—",
          phone: selectedSos.registered_agent.phone_number || "",
          email: selectedSos.registered_agent.email || "",
          address: [
            selectedSos.registered_agent.line1,
            selectedSos.registered_agent.line2,
            selectedSos.registered_agent.city && selectedSos.registered_agent.state
              ? `${selectedSos.registered_agent.city}, ${selectedSos.registered_agent.state} ${selectedSos.registered_agent.zip || ""}`
              : "",
          ].filter(Boolean).join("<br>"),
        });
      }
      if (Array.isArray(selectedSos.officers)) {
        selectedSos.officers.forEach(off => {
          const fullName = [off.first_name, off.middle_name, off.last_name].filter(Boolean).join(" ") || off.company_name || "—";
          sosContacts.push({
            label: off.description || "Officer",
            name: fullName,
            phone: "",
            email: "",
            address: [off.line1, off.line2, off.city && off.state ? `${off.city}, ${off.state} ${off.zip || ""}` : ""].filter(Boolean).join("<br>"),
          });
        });
      }
    }

    const sosEntityCardHtml = `
      <div class="sos-entity-card card">
        <header>
          <h2>SOS Business Entity</h2>
        </header>
        <div class="sos-entity-details">
          ${selectedSos
            ? `
              <div class="sos-item"><strong>Business Name:</strong> ${selectedSos.business_name || "—"}</div>
              ${selectedSos.business_type_desc ? `<div class="sos-item"><strong>Type:</strong> ${selectedSos.business_type_desc}</div>` : ""}
              ${selectedSos.is_perpetual !== undefined ? `<div class="sos-item"><strong>Perpetual:</strong> ${selectedSos.is_perpetual ? "Yes" : "No"}</div>` : ""}
              ${selectedSos.entity_status ? `<div class="sos-item"><strong>Status:</strong> ${formatEntityStatus(selectedSos.entity_status)}</div>` : ""}
              ${selectedSos.entity_status_date ? `<div class="sos-item"><strong>Status Date:</strong> ${selectedSos.entity_status_date}</div>` : ""}
              ${selectedSos.foreign_state ? `<div class="sos-item"><strong>Foreign State:</strong> ${selectedSos.foreign_state}</div>` : ""}
              ${selectedSos.foreign_country ? `<div class="sos-item"><strong>Foreign Country:</strong> ${selectedSos.foreign_country}</div>` : ""}
              ${selectedSos.foreign_date_of_organization ? `<div class="sos-item"><strong>Foreign Org Date:</strong> ${selectedSos.foreign_date_of_organization}</div>` : ""}
              ${selectedSos.addresses && selectedSos.addresses.length > 0
                ? `<div class="sos-item">
                    <strong>Address:</strong>
                    <div>${selectedSos.addresses[0].street_address1 || ""} ${selectedSos.addresses[0].street_address2 || ""}</div>
                    <div>${selectedSos.addresses[0].city || ""}, ${selectedSos.addresses[0].state || ""} ${selectedSos.addresses[0].zip || ""}</div>
                  </div>` : ""
              }
            `
            : `
              ${originalEntityName !== "—"
                ? `<div class="sos-item">
                    <strong>Found Name:</strong> ${originalEntityName}
                  </div>`
                : queryContext.ga_sos_search_had_results === false
                ? `<div class="sos-item">
                    <strong>Status:</strong> No GA SOS match found
                    ${queryContext.sos_search_names_tried && queryContext.sos_search_names_tried.length > 0
                      ? `<div class="sos-tried-names">Searched: ${queryContext.sos_search_names_tried.join(", ")}</div>`
                      : ""
                    }
                  </div>`
                : `<div class="sos-item">
                    <strong>Status:</strong> SOS search not performed
                  </div>`
              }
              ${originalEntityStatus !== "—"
                ? `<div class="sos-item">
                    <strong>Status:</strong> ${originalEntityStatus}
                  </div>`
                : ""
              }
              ${originalEntityLastYear
                ? `<div class="sos-item">
                    <strong>Last Activity Year:</strong> ${originalEntityLastYear}
                  </div>`
                : ""
              }
              ${originalGAEntity.business_type_desc
                ? `<div class="sos-item">
                    <strong>Business Type:</strong> ${originalGAEntity.business_type_desc}
                  </div>`
                : ""
              }
            `
          }
        </div>
      </div>
    `;

    // Relationship & Changes Card (separate small card)
    const relationshipCardHtml = relationshipType || isRenamed || isMerged || hasSuccessor || isWithdrawn || isDissolved || isReinstated
      ? `
        <div class="relationship-card card">
          <header>
            <h3>Relationship & Changes</h3>
          </header>
          <div class="relationship-info">
            ${relationshipType
              ? `<div class="relationship-item">
                  <strong>Relationship Type:</strong> ${relationshipType}
                  ${isCentralized !== null
                    ? ` <span class="centralized-badge ${isCentralized ? 'centralized-yes' : 'centralized-no'}">
                        ${isCentralized ? "(Centralized UP)" : "(Not Centralized)"}
                      </span>`
                    : ""
                  }
                </div>`
              : ""
            }
            ${isRenamed
              ? `<div class="change-flag">✓ Renamed/Rebranded</div>`
              : ""
            }
            ${isMerged
              ? `<div class="change-flag">✓ Merged/Acquired</div>`
              : ""
            }
            ${hasSuccessor && successorName
              ? `<div class="change-flag">✓ Successor Entity: ${successorName}</div>`
              : hasSuccessor
              ? `<div class="change-flag">✓ Has Successor Entity</div>`
              : ""
            }
            ${isWithdrawn
              ? `<div class="change-flag">✓ Withdrawn from GA</div>`
              : ""
            }
            ${isDissolved
              ? `<div class="change-flag">✓ Dissolved/Admin Dissolved</div>`
              : ""
            }
            ${isReinstated
              ? `<div class="change-flag">✓ Reinstated</div>`
              : ""
            }
            ${changeProfile.summary_for_outreach
              ? `<div class="change-summary">
                  <strong>Summary:</strong> ${changeProfile.summary_for_outreach}
                </div>`
              : ""
            }
          </div>
        </div>
      `
      : "";

    const sosContactsHtml = sosContacts.length > 0
      ? `
        <div class="sos-contacts-card card">
          <header>
            <h2>SOS Contacts (selectable)</h2>
          </header>
          <div class="sos-contacts-list">
            ${sosContacts.map((c) => `
              <label class="sos-contact-card">
                <input type="checkbox" disabled>
                <div class="sos-contact-body">
                  <div class="sos-contact-label">${c.label}</div>
                  <div class="sos-contact-name">${c.name}</div>
                </div>
              </label>
            `).join("")}
          </div>
          <p class="sos-contact-note">Selection UI only; adding to contacts to be wired later.</p>
        </div>
      `
      : "";

    const sosEntityHtml = `
      <div class="sos-entity-wrapper">
        ${sosEntityCardHtml}
        ${sosContactsHtml}
      </div>
      ${relationshipCardHtml}
    `;

    // 2. SELECTED/ENTITLED BUSINESS
    // Handle new schema (v12) or legacy schema flexibly
    let selectedEntityName = "—";
    let selectedEntityStatus = "—";
    let selectedEntityLastYear = null;
    let outcome = "—";
    let mailingAddress = "—";
    let businessPhone = "—";
    let businessEmail = null;
    let websiteUrl = null;
    let contactPageUrl = null;
    let googleBusinessStatus = "—";
    let operatingStatus = "—";
    let bestOutreachChannel = "—";
    let whySelected = "";
    let outreachContacts = { phones: [], emails: [], contact_forms: [], named_contacts: [] };
    
    if (isNewSchema) {
      // New schema (v12) structure
      selectedEntityName = selectedEntitledEntity.entitled_business_name || "—";
      operatingStatus = selectedEntitledEntity.operating_status_web || "unknown";
      websiteUrl = selectedEntitledEntity.website || null;
      mailingAddress = selectedEntitledEntity.mailing_address_web || "—";
      bestOutreachChannel = selectedEntitledEntity.best_outreach_channel || "unknown";
      whySelected = selectedEntitledEntity.why_selected || "";
      
      if (selectedEntitledEntity.outreach_contacts) {
        outreachContacts = {
          phones: selectedEntitledEntity.outreach_contacts.phones || [],
          emails: selectedEntitledEntity.outreach_contacts.emails || [],
          contact_forms: selectedEntitledEntity.outreach_contacts.contact_forms || [],
          named_contacts: selectedEntitledEntity.outreach_contacts.named_contacts || []
        };
        businessPhone = outreachContacts.phones.length > 0 ? outreachContacts.phones[0] : "—";
        businessEmail = outreachContacts.emails.length > 0 ? outreachContacts.emails[0] : null;
        contactPageUrl = outreachContacts.contact_forms.length > 0 ? outreachContacts.contact_forms[0] : null;
      }
      
      // Determine outcome from selected rank
      if (selectedEntitledEntity.selected_rank) {
        outcome = `Selected (Rank ${selectedEntitledEntity.selected_rank})`;
      }
    } else {
      // Legacy schema structure
      const selectedEntity = identification.selected_entity || {};
      selectedEntityName = selectedEntity.legal_name || identification.preferred_outreach_entity_name || "—";
      selectedEntityStatus = formatEntityStatus(selectedEntity.entity_status);
      const selectedEntityStatusDate = selectedEntity.entity_status_date;
      selectedEntityLastYear = extractYearFromDate(selectedEntityStatusDate);
      outcome = formatOutcome(identification.outcome);
      
      mailingAddress = addresses.best_mailing_address || "—";
      businessPhone = businessChannels.general_phone || "—";
      businessEmail = businessChannels.general_email || null;
      websiteUrl = businessChannels.website_url || null;
      contactPageUrl = businessChannels.contact_page_url || null;
      googleBusinessStatus = formatGoogleBusinessStatus(businessChannels.google_business_status);
    }

    const selectedBusinessHtml = `
      <div class="selected-business-card card">
        <header>
          <h2>Selected/Entitled Business</h2>
          <div class="outcome-badge">${outcome}</div>
        </header>
        <div class="selected-business-details">
          <div class="business-info">
            <div class="info-item">
              <strong>Name:</strong> ${selectedEntityName}
            </div>
            ${isNewSchema && operatingStatus !== "unknown"
              ? `<div class="info-item">
                  <strong>Operating Status:</strong> ${operatingStatus}
                </div>`
              : !isNewSchema && selectedEntityStatus !== "—"
              ? `<div class="info-item">
                  <strong>Status:</strong> ${selectedEntityStatus}
                </div>`
              : ""
            }
            ${!isNewSchema && selectedEntityLastYear
              ? `<div class="info-item">
                  <strong>Last Activity Year:</strong> ${selectedEntityLastYear}
                </div>`
              : ""
            }
            ${mailingAddress !== "—"
              ? `<div class="info-item">
                  <strong>Mailing Address:</strong> ${mailingAddress}
                </div>`
              : ""
            }
            ${businessPhone !== "—"
              ? `<div class="info-item">
                  <strong>Phone:</strong> ${businessPhone}
                  ${isNewSchema && outreachContacts.phones.length > 1
                    ? ` <span class="muted">(+${outreachContacts.phones.length - 1} more)</span>`
                    : ""
                  }
                </div>`
              : ""
            }
            ${websiteUrl
              ? `<div class="info-item">
                  <strong>Website:</strong> <a href="${websiteUrl}" target="_blank" rel="noopener">${websiteUrl}</a>
                </div>`
              : ""
            }
            ${!isNewSchema && googleBusinessStatus !== "—"
              ? `<div class="info-item">
                  <strong>Google Business Status:</strong> ${googleBusinessStatus}
                </div>`
              : ""
            }
            ${businessEmail
              ? `<div class="info-item">
                  <strong>Email:</strong> <a href="mailto:${businessEmail}">${businessEmail}</a>
                  ${isNewSchema && outreachContacts.emails.length > 1
                    ? ` <span class="muted">(+${outreachContacts.emails.length - 1} more)</span>`
                    : ""
                  }
                </div>`
              : ""
            }
            ${contactPageUrl
              ? `<div class="info-item">
                  <strong>Contact Page:</strong> <a href="${contactPageUrl}" target="_blank" rel="noopener">${contactPageUrl}</a>
                </div>`
              : ""
            }
            ${isNewSchema && bestOutreachChannel !== "unknown"
              ? `<div class="info-item">
                  <strong>Best Outreach Channel:</strong> ${formatPreferredOutreachMethod(bestOutreachChannel)}
                </div>`
              : ""
            }
            ${isNewSchema && whySelected
              ? `<div class="info-item">
                  <strong>Why Selected:</strong> ${whySelected}
                </div>`
              : ""
            }
          </div>
        </div>
      </div>
    `;

    // 3. CONTACTS
    // Handle new schema (v12) or legacy schema flexibly
    let displayContacts = [];
    if (isNewSchema) {
      // New schema: use named_contacts from selected_entitled_entity.outreach_contacts
      displayContacts = outreachContacts.named_contacts || [];
    } else {
      // Legacy schema: use people_contacts structure
      const topContacts = peopleContacts.top_contacts || [];
      const allContacts = peopleContacts.contacts || [];
      displayContacts = topContacts.length > 0 ? topContacts : allContacts.slice(0, 5);
    }

    const contactsHtml = displayContacts.length > 0
      ? `
        <div class="contacts-section">
          <h3>Contacts</h3>
          <div class="contacts-grid">
            ${displayContacts.map((contact, idx) => `
              <div class="contact-card">
                <div class="contact-header">
                  <h4>${contact.name || "—"}</h4>
                  ${contact.role_bucket ? `<span class="role-bucket-badge">${formatRoleBucket(contact.role_bucket)}</span>` : ""}
                </div>
                <div class="contact-details">
                  ${contact.role_or_title ? `<div><strong>Role/Title:</strong> ${contact.role_or_title}</div>` : ""}
                  ${contact.contact_type ? `<div><strong>Contact Type:</strong> ${formatContactType(contact.contact_type)}</div>` : ""}
                  ${contact.phone ? `<div><strong>Phone:</strong> ${contact.phone}</div>` : ""}
                  ${contact.email ? `<div><strong>Email:</strong> <a href="mailto:${contact.email}">${contact.email}</a></div>` : ""}
                  ${contact.mailing_address ? `<div><strong>Mailing Address:</strong> ${contact.mailing_address}</div>` : ""}
                  <div class="contact-meta">
                    <span class="contact-source">Source: ${formatSource(contact.source || "unknown")}</span>
                    ${contact.priority_rank ? `<span class="priority-rank">Priority: ${contact.priority_rank}</span>` : ""}
                  </div>
                </div>
              </div>
            `).join("")}
          </div>
          ${!isNewSchema && peopleContacts.contacts && peopleContacts.contacts.length > displayContacts.length
            ? `<div class="contacts-note">
                Showing top ${displayContacts.length} of ${peopleContacts.contacts.length} contacts
              </div>`
            : ""
          }
        </div>
      `
      : `
        <div class="contacts-section">
          <h3>Contacts</h3>
          <p class="muted">No contacts extracted.</p>
        </div>
      `;

    // 4. RECOMMENDATIONS
    const hasActionableContact = integrationFlags.has_actionable_contact;
    const needsBusinessEnrichment = integrationFlags.needs_business_enrichment;
    const needsPeopleSearch = integrationFlags.needs_people_search;
    const needsGooglePlaces = integrationFlags.needs_google_places;
    const needsOtherStateSOS = integrationFlags.needs_other_state_sos;
    const needsManualReview = integrationFlags.needs_manual_review;
    const lookupNeeded = dataGaps.lookup_needed;
    const missingDataPoints = dataGaps.missing_data_points || [];
    const templateCategory = formatTemplateCategory(communicationProfile.template_category);
    const communicationNotes = communicationProfile.notes;
    const noWebPresence = analysis.no_web_presence || false;

    const recommendationsHtml = `
      <div class="recommendations-card">
        <h3>Recommendations & Next Steps</h3>
        <div class="recommendations-details">
          ${noWebPresence
            ? `<div class="no-web-presence-notice">
                <strong>ℹ️ Limited Internet History</strong>
                <p>No web presence found for this business. This is common for small local businesses. SOS data and Google Places information (if available) are shown above.</p>
              </div>`
            : ""
          }
          
          <div class="actionable-contact-status">
            <strong>Actionable Contact Available:</strong>
            <span class="actionable-badge ${hasActionableContact ? 'actionable-yes' : 'actionable-no'}">
              ${hasActionableContact ? "Yes" : "No"}
            </span>
          </div>
          
          ${templateCategory !== "—"
            ? `<div class="template-category">
                <strong>Template Category:</strong> ${templateCategory}
              </div>`
            : ""
          }
          
          ${communicationNotes
            ? `<div class="communication-notes">
                <strong>Notes:</strong> ${communicationNotes}
              </div>`
            : ""
          }
          
          ${needsBusinessEnrichment || needsPeopleSearch || needsGooglePlaces || needsOtherStateSOS || needsManualReview || lookupNeeded
            ? `<div class="enrichment-needs">
                <h4>External Contact Enrichment Required</h4>
                <ul>
                  ${needsBusinessEnrichment ? `<li>Business enrichment needed - no finance contacts found for active mid/large company</li>` : ""}
                  ${needsPeopleSearch ? `<li>People search needed - only person names exist but no current address/phone/email</li>` : ""}
                  ${needsGooglePlaces ? `<li>Google Places lookup needed - address/phone/status are missing or conflicting</li>` : ""}
                  ${needsOtherStateSOS ? `<li>Other state SOS search needed - foreign registration or likely formation elsewhere</li>` : ""}
                  ${needsManualReview ? `<li>Manual review needed - multiple plausible successors or major conflicts</li>` : ""}
                  ${lookupNeeded && !needsBusinessEnrichment && !needsPeopleSearch && !needsGooglePlaces && !needsOtherStateSOS && !needsManualReview
                    ? `<li>Additional lookup needed - missing data points identified</li>`
                    : ""
                  }
                </ul>
              </div>`
            : ""
          }
          
          ${missingDataPoints.length > 0
            ? `<div class="missing-data">
                <h4>Missing Data Points</h4>
                <ul>
                  ${missingDataPoints.map(point => `<li>${point}</li>`).join("")}
                </ul>
              </div>`
            : ""
          }
          
          ${!hasActionableContact && !needsBusinessEnrichment && !needsPeopleSearch && !needsGooglePlaces && !needsOtherStateSOS && !needsManualReview && missingDataPoints.length === 0
            ? `<div class="no-action-needed">
                <p>No additional enrichment needed at this time.</p>
              </div>`
            : ""
          }
        </div>
      </div>
    `;

    container.innerHTML = `
      ${sosEntityHtml}
      ${selectedBusinessHtml}
      ${contactsHtml}
      ${recommendationsHtml}
    `;
  }

  function renderSosSelector(container, state, handlers) {
    const optionsHtml = state.records.length > 0
      ? `
        <label for="sos-select">Select SOS business</label>
        <select id="sos-select" class="sos-select">
          ${state.records.map((rec, idx) => `
            <option value="${idx}" ${idx === state.selectedIndex ? "selected" : ""}>
              ${rec.business_name || "Unnamed"} — ${rec.entity_status || "Unknown"} (${rec.entity_status_date || "n/a"})
            </option>
          `).join("")}
        </select>
      `
      : `<p class="muted">No SOS matches found.</p>`;

    const flipBtn = state.flipAllowed
      ? `<button class="btn btn-ghost" id="sos-flip-btn" ${state.flipApplied ? "disabled" : ""}>Try flipped search</button>`
      : "";

    container.classList.remove("error-state");
    container.innerHTML = `
      <div class="sos-selector">
        <h3>SOS Search Results</h3>
        <div class="sos-meta">Search name used: <strong>${state.searchNameUsed || "—"}</strong> ${state.flipApplied ? "(flipped)" : ""}</div>
        ${optionsHtml}
        <div class="sos-actions">
          ${flipBtn}
          <button class="btn btn-primary" id="run-analysis-btn" ${state.records.length === 0 ? "disabled" : ""}>Run AI with selected SOS</button>
          ${state.records.length === 0 ? "" : `<button class="btn btn-link" id="run-analysis-nosos-btn">Run without SOS</button>`}
          ${state.records.length === 0 ? `<button class="btn btn-secondary" id="run-analysis-nosos-btn-empty">Run without SOS</button>` : ""}
        </div>
      </div>
    `;

    const flipButton = document.getElementById("sos-flip-btn");
    if (flipButton) {
      flipButton.addEventListener("click", () => handlers.onFlip());
    }

    const runBtn = document.getElementById("run-analysis-btn");
    if (runBtn) runBtn.addEventListener("click", () => handlers.onRun());

    const runNoSosBtn = document.getElementById("run-analysis-nosos-btn");
    if (runNoSosBtn) runNoSosBtn.addEventListener("click", () => handlers.onRunWithoutSos());

    const runNoSosBtnEmpty = document.getElementById("run-analysis-nosos-btn-empty");
    if (runNoSosBtnEmpty) runNoSosBtnEmpty.addEventListener("click", () => handlers.onRunWithoutSos());
  }

  window.EntityIntel = window.EntityIntel || {};
  window.EntityIntel.render = {
    renderResult,
    renderSosSelector,
  };
})();
