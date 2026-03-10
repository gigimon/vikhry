// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const repository = process.env.GITHUB_REPOSITORY ?? '';
const repositoryOwner = process.env.GITHUB_REPOSITORY_OWNER ?? '';
const repositoryName = repository.split('/')[1] ?? '';
const isGitHubPagesBuild =
	process.env.GITHUB_ACTIONS === 'true' && repositoryOwner !== '' && repositoryName !== '';

// https://astro.build/config
export default defineConfig({
	site: isGitHubPagesBuild ? `https://${repositoryOwner}.github.io` : undefined,
	base: isGitHubPagesBuild ? `/${repositoryName}` : undefined,
	integrations: [
		starlight({
			title: 'vikhry',
			disable404Route: true,
		}),
	],
});
