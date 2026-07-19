export default function Stars({ rating }) {
  if (!rating) return <span className="muted stars-empty">Unrated</span>;
  return (
    <span className="stars" aria-label={`${rating} out of 5 stars`}>
      {'★'.repeat(rating)}
      {'☆'.repeat(5 - rating)}
    </span>
  );
}
