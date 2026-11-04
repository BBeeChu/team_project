# Security policy

Use this policy to report suspected vulnerabilities in Auctopus. Repository maintainers handle reports through a private channel arranged using the process below.

## Reporting scope

Reports may concern the Python package, command-line interface, SSH transport, handling of API keys, or construction and execution of remote agent commands. In the private report, explain how the suspected defect could expose information, permit unintended access or execute an unintended command.

For execution permissions, instrument limits and approval responsibilities, read [Safety](docs/safety.md). This policy covers software vulnerabilities. Use the private reporting process for vulnerability details even when the concern also involves instrument operation.

## Request a private channel

To arrange a private conversation with the maintainers, use this process:

1. Open a blank issue in the [Auctopus repository](https://github.com/E-zClap/auctopus).
2. Set its title to **Security contact request**.
3. Include only a request for a private reporting channel. Do not describe the problem or attach evidence, including synthetic examples.
4. Wait until a maintainer has arranged a private channel before sharing the report. Send the details only through that channel.

The issue is public. Keep all problem details out of its body and comments, including affected components, exploit steps, logs and screenshots. Do not disclose the vulnerability in a public pull request while requesting contact.

## Prepare the private report

Prepare the following information for the private channel:

- The Auctopus version or commit, and whether you changed the code.
- The relevant environment, including Python version, operating system, transport, remote agent and account permissions where applicable.
- The affected part of Auctopus and the minimal configuration needed to reach it.
- Reproduction steps, the command used, and expected and observed behaviour.
- The likely impact, the access required and any limits on your findings.
- Relevant redacted evidence, such as a short log excerpt or command output.

In the private report, use minimal synthetic prompts, instrument descriptions and data, example hostnames, and redacted configuration excerpts. Remove secrets and private material, including API keys, private host details, personal information, the authors' unpublished study prompts and private instrument descriptions.

Share only what is needed to investigate the defect. If redaction prevents reproduction, explain what context is missing in the private channel without disclosing the private material.
