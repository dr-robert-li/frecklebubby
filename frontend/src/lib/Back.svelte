<script lang="ts">
	import Icon from './Icon.svelte';
	let { title }: { title: string } = $props();
</script>

<svelte:head><title>{title} · Frecklebubby</title></svelte:head>
<a class="back" href="/settings"><Icon name="left" size={20} /> Settings</a>
<h1>{title}</h1>

<style>
	.back {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		min-height: 44px;
		text-decoration: none;
	}
</style>
