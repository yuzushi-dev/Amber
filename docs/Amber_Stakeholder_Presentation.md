# Amber: The Sovereign AI Knowledge Assistant for Carbonio

**Strategic Overview | January 2026**

---

## Introduction

Amber represents a paradigm shift in how organizations interact with their corporate knowledge. In an era where enterprises are drowning in data spread across email, chat, documents, and wikis, Amber emerges as a private, self-hosted AI brain that transforms fragmented information into actionable intelligence—without ever exposing sensitive data to external cloud services.

This document outlines Amber's product vision, financial advantages, partner opportunities, and regional market fit for stakeholders evaluating sovereign AI solutions.

---

## The Product Vision

### Understanding Amber

At its core, Amber is a **private brain for your organization**. Unlike cloud-based AI assistants that require sending your data to third-party servers, Amber operates entirely within your network perimeter. It is a self-hosted artificial intelligence system designed to truly understand your organization's data by connecting diverse sources—Email, Chat, Files, and enterprise Wikis—into a unified Knowledge Graph.

The fundamental promise of Amber is straightforward yet powerful: it delivers precise, synthesized answers rather than lists of links. When a user asks a question, Amber doesn't simply point them to relevant documents and leave them to piece together the answer. Instead, it comprehends the question, retrieves relevant context from across all connected sources, synthesizes a coherent response, and cites its sources for full transparency and verifiability.

Most critically, **100% of this processing happens on-premise**. No data ever leaves your network, making Amber suitable for the most security-conscious organizations and regulatory environments.

### The GraphRAG Advantage

To appreciate what makes Amber different, it's important to understand the limitations of traditional approaches to enterprise search and AI-assisted retrieval.

**Standard enterprise search** relies on keyword matching. When users search for information, the system looks for documents containing those specific words. This approach suffers from low relevance (searching for "Q3 revenue" won't find a document that discusses "third quarter earnings"), produces disconnected results requiring manual synthesis, and fundamentally only helps users find documents—it doesn't help them solve problems.

**Standard RAG (Retrieval-Augmented Generation)** systems improve on this by using semantic similarity. They understand that "Q3 revenue" and "third quarter earnings" are related concepts. However, they still operate on individual text chunks without understanding the relationships between entities across your knowledge base.

**Amber's GraphRAG architecture** takes a fundamentally different approach. Beyond semantic understanding, Amber builds a Knowledge Graph that maps the relationships between entities—people, projects, concepts, documents, and events. When answering questions, Amber can traverse these relationships to find relevant context that keyword search or simple semantic similarity would miss entirely.

Consider a question like: "What projects is John Smith working on, and who else is involved in each?" Standard search returns documents mentioning John Smith. Standard RAG might find some project information from a single document. Amber's GraphRAG traverses the Knowledge Graph to identify all PROJECT entities linked to the John Smith PERSON entity, then follows WORKS_ON relationships to find all collaborators—synthesizing a complete, accurate answer with proper citations.

The difference can be summarized as: Standard search helps you find documents. Amber helps you solve problems.

### Core Capabilities

Amber's capabilities fall into two complementary categories: the Knowledge Engine and Agentic Actions.

**The Knowledge Engine** handles the ingestion, understanding, and retrieval of organizational knowledge:

- **Multi-format document ingestion** processes PDFs, Word documents, HTML pages, and more, extracting not just text but preserving document structure and metadata.
- **Enterprise system integration** connects directly to Carbonio Mail and Chat, synchronizes with Confluence wikis and Zendesk knowledge bases, creating a unified knowledge layer across previously siloed systems.
- **Intelligent entity extraction** uses large language models to identify entities (people, organizations, concepts, projects) and their relationships, building the Knowledge Graph automatically.
- **Incremental real-time updates** ensure the knowledge base stays current. When documents change or new emails arrive, Amber processes the updates without requiring a full rebuild.

**Agentic Actions** extend Amber beyond passive question-answering into active assistance:

- **Calendar integration** allows Amber to query availability when users ask scheduling questions like "When can the team meet next week?"
- **Contextual chat search** enables Amber to find relevant conversation threads based on topic and context, not just keywords.
- **Policy-based drafting** means Amber can draft responses based on organizational policies and historical precedent.
- **Multi-step reasoning** through the Drift Search capability allows Amber to handle complex questions that require iterative exploration—following threads of information across multiple hops in the Knowledge Graph.

---

## The Financial Case

### Understanding the Cost Drivers

To build a credible financial model, we analyzed over 6,600 real-world interactions from production Amber deployments. This analysis revealed several key insights:

The **average query consumes approximately 2,100 tokens**, encompassing both the context retrieved and the response generated. This metric is crucial for cost modeling because token consumption directly drives costs for both cloud API and on-premise inference.

The **primary cost driver is generation, accounting for 95% of total costs**. Embedding (for search) is computationally inexpensive by comparison. This means cost optimization efforts should focus on generation efficiency.

With these empirical metrics, we can model costs accurately for a typical deployment of 1,000 users.

### Three-Year Cost Comparison

The financial difference between cloud-based AI and on-premise Amber is substantial and grows over time.

**Cloud API (GPT-4o) costs approximately $2,210 per month** for a 1,000-user organization with typical usage patterns. Over three years, this accumulates to approximately $80,000. However, several factors make this figure potentially conservative:

- API pricing trends show consistent increases over time
- Usage typically grows as users discover value in the system  
- Peak usage periods can cause unexpected overages
- The organization builds no lasting asset—they are renting access

**Amber On-Premise costs approximately $700 per month when amortized** over the hardware lifecycle. The three-year total comes to approximately $25,000. This includes:

- GPU server hardware (which becomes an owned asset)
- Software licensing
- Power and cooling (minimal for single-server deployments)

The trend line is fundamentally different: while cloud costs increase over time with usage growth and pricing changes, on-premise costs remain flat, providing an inflation hedge. After three years, the organization owns hardware that retains residual value.

Perhaps most importantly, on-premise deployment means **data never leaves the organizational perimeter**. For organizations with regulatory requirements or competitive sensitivity, this isn't just a security preference—it's a business requirement.

### The Partner Revenue Opportunity

The $55,000 three-year savings versus cloud represents a 68% cost reduction for customers. But for partners, this same gap represents something more valuable: a **revenue opportunity**.

When a customer uses cloud AI services, their ongoing spend flows to OpenAI, Microsoft, or Google—companies that have no relationship with the local partner. The partner is cut out of the value chain entirely.

With Amber, the economic flow reverses. Instead of paying a cloud provider, customers pay partners for:

- Hardware procurement and margins
- Software licensing (often with recurring maintenance)
- Professional services for deployment and customization
- Ongoing support contracts

Revenue shifts from **rent** (paying a cloud provider) to **assets plus services** (paying the partner). The partner captures value that would otherwise leave the local economy entirely.

---

## The Partner Strategy

### Four Revenue Streams

Amber creates four distinct revenue opportunities for partners, each with different characteristics and margin profiles.

**Hardware sales** represent the most immediately tangible opportunity. Partners can capture margin on GPU servers (typically 15-25% depending on the configuration), own the refresh cycle (creating recurring hardware revenue every 3-4 years), and bundle storage and networking equipment. For a typical 1,000-user deployment, hardware represents $15,000-20,000 in sales with corresponding partner margins.

**Appliance/license sales** provide recurring software revenue. Amber licensing follows a subscription model, meaning partners can build a base of recurring revenue rather than relying solely on one-time hardware sales. Combined hardware-plus-license bundling enables higher ticket sizes and simpler customer purchasing.

**Professional services** represent perhaps the highest-margin opportunity. Partners can deliver:

- **AI Readiness Assessments**: Evaluating customer data quality, infrastructure, and use cases (typically $2,000-5,000)
- **Data Hygiene Audits**: Cleaning, deduplicating, and structuring data for optimal AI performance ($5,000-15,000)
- **Custom Connector Development**: Building integrations with proprietary systems not covered by standard connectors ($10,000-30,000)
- **Training and enablement**: User training, administrator training, and documentation ($3,000-10,000)

**Sovereign MSP Hosting** enables partners to offer Amber as a managed service. For customers who lack IT infrastructure or expertise to run Amber themselves, partners can host dedicated or shared Amber instances in their own data centers. This creates recurring monthly revenue ($2,000-5,000 for dedicated instances) while still maintaining the sovereign promise—data never leaves the partner's regional infrastructure.

### Why Partners Choose Amber

Beyond the financial opportunity, Amber provides strategic benefits that strengthen partner businesses.

**Differentiation** in an increasingly commoditized market. While every IT partner offers cloud migration and managed services, few can credibly claim "We offer true Private AI." This positions partners uniquely in competitive situations.

**Customer stickiness** that approaches permanence. Once an organization has built their knowledge graph—mapping all the entities, relationships, and institutional knowledge across their data—switching costs become enormous. The knowledge graph represents organizational understanding that would need to be rebuilt from scratch. Properly deployed, Amber creates customers for life.

**Defensibility against hyperscaler encroachment**. Microsoft 365 Copilot represents an existential threat to many partners: once customers adopt Microsoft's AI assistant, the partner is disintermediated. Amber provides a strategic counter-narrative. Partners can position on-premise AI as superior for data sovereignty, compliance, and cost—protecting their customer relationships.

**Relationship ownership** remains with the partner, not the technology vendor. When customers use cloud AI, their relationship is increasingly with Microsoft or OpenAI. With Amber, the partner remains the primary vendor, the trusted advisor, and the point of contact.

---

## Regional Market Fit

### The Global Sovereignty Imperative

Across emerging markets worldwide, a consistent pattern has emerged: increasing resistance to Western cloud AI services. This resistance isn't irrational protectionism—it stems from legitimate, concrete risks.

**Surveillance risk** concerns organizations and governments about data accessibility under laws like the US Patriot Act and CLOUD Act. Data stored with US-headquartered cloud providers is legally accessible to US government agencies under certain circumstances, regardless of where the data is physically located. For many organizations—particularly government agencies, defense contractors, and competitive enterprises—this exposure is unacceptable.

**Sanction risk** has become increasingly tangible. Organizations have witnessed cloud services terminated without notice when sanctions are imposed. For any organization with geopolitical exposure, relying on US cloud services creates a "kill switch" that can be activated by political decisions beyond their control.

**Currency risk** affects financial planning. USD-denominated cloud services create OpEx volatility for organizations operating in other currencies. Exchange rate fluctuations can cause significant budget variances, making financial planning difficult and often resulting in effective price increases.

Amber solves all three risks simultaneously through 100% on-premise deployment. Once deployed, Amber requires no ongoing connection to US services, no USD payments, and no data exposure.

### Regional Analysis

**Russia and CIS markets** face perhaps the most acute version of these challenges. Law 152-FZ requires personal data of Russian citizens to be stored on servers located within Russia. Sanctions have made payment to many Western technology vendors legally problematic or impossible. The need for sanction-proof IT infrastructure is not theoretical—it's operational reality.

For these markets, Amber's 100% offline capability is essential. The system can be deployed in entirely air-gapped environments with no internet connectivity whatsoever. All inference runs locally on owned hardware, eliminating any ongoing vendor dependency.

**Brazil and Latin American markets** operate under the LGPD (Lei Geral de Proteção de Dados), Brazil's comprehensive data protection law modeled on GDPR. Violations carry substantial fines—up to 2% of Brazilian revenue. Beyond compliance, organizations in the region increasingly seek to avoid heavy USD-denominated operating expenses that create budget volatility.

Partner-hosted sovereign cloud provides the ideal solution for this market. Partners can operate Amber instances within Brazil using BRL-denominated contracts, providing LGPD compliance, currency stability, and local support simultaneously.

**Southeast Asian markets, particularly Vietnam and Indonesia**, have implemented increasingly strict data residency requirements. Vietnam's Decree 53 requires certain data categories to be stored on local servers. Both countries have articulated national strategies for "Digital Independence" and "National Digital Transformation."

Amber enables local system integrators to participate in these national initiatives by building "National AI Clouds"—sovereign AI infrastructure that serves government and enterprise customers while keeping data within national borders. This alignment with government priorities creates partnership opportunities at the national strategic level.

---

## Conclusion

Amber represents a fundamental shift in how organizations can deploy AI capabilities: sovereign, intelligent, and profitable.

**Sovereign** because data never leaves organizational or national boundaries. In a world of increasing data regulation and geopolitical tension, sovereignty is not optional—it's required.

**Intelligent** because GraphRAG technology delivers genuinely better answers than traditional search or simple RAG systems. The Knowledge Graph approach understands relationships and context, synthesizing complete answers rather than returning document lists.

**Profitable** because the economics favor both customers (68% savings versus cloud) and partners (capturing revenue that would otherwise flow to US hyperscalers).

For partners ready to differentiate, build lasting customer relationships, and capture the AI opportunity, Amber provides the platform. For organizations requiring data sovereignty without sacrificing AI capabilities, Amber provides the solution.

**Amber: Empowering Partners to Own the AI Future.**

---

*This document provides a strategic overview of Amber for stakeholder evaluation. For technical specifications, deployment requirements, and pricing details, please contact your Zextras partner representative.*
