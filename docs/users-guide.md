# Episodic User's Guide

Welcome to the Episodic user's guide! This document will help you get started
with creating AI-powered podcasts once the platform is ready.

## 🚧 Current Status

**This guide is under construction.** Episodic is in active early development
(Phase 1 of 6), and most features described here are planned but not yet
implemented.

See [`roadmap.md`](roadmap.md) for the current development status and timeline.

## What You'll Find Here (Eventually)

This guide will cover:

### Getting Started

- Installing and configuring the Episodic CLI
- Setting up your first podcast series
- Creating series profiles and episode templates
- Understanding the workflow from source documents to finished audio

### Content Creation

- Uploading and ingesting source documents
- Working with TEI (Text Encoding Initiative) canonical content
- Tracking ingestion jobs, source weighting decisions, and provenance metadata
- Configuring content weighting and conflict resolution
- Managing episode metadata and show notes
- Database schema integrity is validated automatically in CI so that canonical
  content storage remains consistent across releases
- Repository and transactional integrity are validated by integration tests
  running against a real PostgreSQL engine, covering persistence round-trips,
  rollback behaviour, and constraint enforcement
- Multi-source ingestion normalises heterogeneous sources (transcripts,
  briefs, Really Simple Syndication (RSS) feeds, press releases, and research
  notes) into canonical TEI episodes. Source weighting heuristics automatically
  compute priority scores based on quality, freshness, and reliability.
  Conflicts between competing sources are resolved using a weighting matrix,
  with all source material retained for audit regardless of whether it was
  preferred or rejected. Weighting coefficients are configurable per series
  profile

### Quality & Compliance

- Setting up brand guidelines and compliance rules
- Configuring multi-layer quality assurance checks
- Using the editorial approval workflow
- Reviewing approval states and audit history for canonical episodes
- Reviewing and approving generated content

### Audio Production

- Selecting voice personas and TTS settings
- Choosing background music and sound effects
- Understanding the mixing and mastering process
- Previewing and downloading final episodes

### Cost Management

- Understanding token usage and metering
- Setting budget limits per user or organization
- Monitoring spend and usage dashboards
- Optimizing costs with model tiering

### Advanced Topics

- Customizing LangGraph workflows
- Integrating with external systems via API
- Managing multi-tenant deployments
- Troubleshooting common issues

## In the Meantime

While we're building out the platform, you can:

1. **Explore the architecture**: Read
   [`episodic-podcast-generation-system-design.md`](episodic-podcast-generation-system-design.md)
    to understand how Episodic works under the hood.

2. **Check the roadmap**: See [`roadmap.md`](roadmap.md) to track development
   progress and see what's coming next.

3. **Review the infrastructure**: Learn about the Kubernetes-based deployment in
   [`infrastructure-design.md`](infrastructure-design.md).

4. **Contribute**: If you're interested in contributing, check out
   [`../AGENTS.md`](../AGENTS.md) for guidelines and code quality standards.

## Questions or Feedback?

This project is developed by **df12 Productions**. Visit
[https://df12.studio](https://df12.studio) for more information.

______________________________________________________________________

_This guide will be updated as features are implemented. Check back regularly
for the latest information!_
